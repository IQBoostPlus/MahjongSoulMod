"""Validate provenance/splits and evaluate manually annotated real screenshots.

No mouse operations, captures, template synthesis or label inference occur here.
Use --check for a dependency-free manifest check, --split development for known
debug samples, and --split test only for previously unused capture sessions.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BUTTONS = ('pon', 'chi', 'kan', 'riichi', 'ron', 'tsumo', 'pass')


def validate_manifest(path):
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema_version') != 1 or not isinstance(data.get('samples'), list):
        raise ValueError('Expected schema_version=1 and a samples array')
    ids, hashes, sessions = set(), {}, {}
    for sample in data['samples']:
        sid = sample.get('id')
        if not isinstance(sid, str) or not sid or sid in ids:
            raise ValueError(f'Duplicate or invalid sample id: {sid}')
        ids.add(sid)
        split = sample.get('split')
        if split not in ('development', 'test'):
            raise ValueError(f'{sid}: split must be development or test')
        session = sample.get('session_id')
        if not isinstance(session, str) or not session:
            raise ValueError(f'{sid}: session_id is required')
        if session in sessions and sessions[session] != split:
            raise ValueError(f'{sid}: session leaks across splits')
        sessions[session] = split
        if sample.get('status') not in ('pending', 'reviewed'):
            raise ValueError(f'{sid}: status must be pending or reviewed')
        source = sample.get('source', {})
        if (source.get('kind') not in ('local_capture', 'external_unknown')
                or not isinstance(source.get('used_for_tuning'), bool)
                or not source.get('provenance')):
            raise ValueError(f'{sid}: source kind/provenance/used_for_tuning required')
        if split == 'test' and (source['used_for_tuning'] or source['kind'] != 'local_capture'):
            raise ValueError(f'{sid}: test requires unused local captures with known provenance')
        relative = sample.get('image')
        if not isinstance(relative, str) or not relative:
            raise ValueError(f'{sid}: image path is required')
        image = (path.parent / relative).resolve()
        if not image.is_relative_to(path.parent):
            raise ValueError(f'{sid}: image escapes dataset directory')
        if not image.is_file():
            raise ValueError(f'{sid}: missing image {relative}; restore dataset images first')
        digest = hashlib.sha256(image.read_bytes()).hexdigest()
        if digest != sample.get('sha256'):
            raise ValueError(f'{sid}: image SHA256 mismatch')
        if digest in hashes:
            raise ValueError(f'{sid}: duplicate image content ({hashes[digest]})')
        hashes[digest] = sid
        size = sample.get('size')
        if not isinstance(size, list) or len(size) != 2 or any(type(n) is not int or n <= 0 for n in size):
            raise ValueError(f'{sid}: size must be [width, height]')
        annotated = False
        for section, key in (('hand', 'tiles'), ('buttons', 'visible')):
            ann = sample.get(section)
            if ann is None:
                continue
            roi = ann.get('roi')
            if (not isinstance(roi, list) or len(roi) != 4
                    or any(type(n) not in (float, int) or not math.isfinite(n) for n in roi)
                    or not 0 <= roi[0] < roi[2] <= 1 or not 0 <= roi[1] < roi[3] <= 1):
                raise ValueError(f'{sid}: invalid {section} normalized ROI')
            labels = ann.get(key)
            if labels is None:
                continue
            if not isinstance(labels, list):
                raise ValueError(f'{sid}: {key} must be an array or null')
            if section == 'hand' and (not labels or any(type(t) is not int or not -1 <= t <= 36 for t in labels)):
                raise ValueError(f'{sid}: hand labels must be nonempty tile IDs -1..36')
            if section == 'buttons' and (len(set(labels)) != len(labels) or any(t not in BUTTONS for t in labels)):
                raise ValueError(f'{sid}: invalid or duplicate button names')
            annotated = True
        if sample['status'] == 'reviewed' and (not annotated or not sample.get('reviewer')):
            raise ValueError(f'{sid}: reviewed sample needs explicit labels and reviewer')
        sample['_image_path'] = image
    return data


def align_tiles(expected, predicted):
    """Levenshtein alignment: insertion/deletion cannot hide behind zip()."""
    n, m = len(expected), len(predicted)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            dp[i][j] = min(dp[i-1][j-1] + (expected[i-1] != predicted[j-1]),
                           dp[i-1][j] + 1, dp[i][j-1] + 1)
    pairs, i, j = [], n, m
    while i or j:
        if i and j and dp[i][j] == dp[i-1][j-1] + (expected[i-1] != predicted[j-1]):
            pairs.append((expected[i-1], predicted[j-1])); i -= 1; j -= 1
        elif i and dp[i][j] == dp[i-1][j] + 1:
            pairs.append((expected[i-1], None)); i -= 1
        else:
            pairs.append((None, predicted[j-1])); j -= 1
    return list(reversed(pairs)), dp[n][m]


def ratio(num, den):
    return num / den if den else None


def aggregate(records):
    counts = Counter()
    tile_classes = {}
    for row in records:
        if 'expected_hand' in row:
            expected, predicted = row['expected_hand'], row['predicted_hand']
            pairs, edits = align_tiles(expected, predicted)
            counts['hand_frames'] += 1
            counts['exact_hands'] += expected == predicted
            counts['sequence_edits'] += edits
            counts['sequence_slots'] += max(len(expected), len(predicted))
            for gt, pred in pairs:
                if gt is None:
                    counts['extra_detections'] += 1
                elif gt == -1:
                    counts['back_regions'] += 1
                    counts['back_false_accepts'] += pred is not None and pred != -1
                else:
                    counts['known_tiles'] += 1
                    counts['correct_tiles'] += gt == pred
                    counts['known_rejections'] += pred in (None, -1)
                    stats = tile_classes.setdefault(str(gt), {'correct': 0, 'total': 0})
                    stats['total'] += 1
                    stats['correct'] += gt == pred
        if 'expected_buttons' in row:
            expected, predicted = set(row['expected_buttons']), set(row['predicted_buttons'])
            counts['button_frames'] += 1
            if not expected:
                counts['negative_button_frames'] += 1
                counts['negative_button_false_positives'] += bool(predicted)
            counts['button_tp'] += len(expected & predicted)
            counts['button_fp'] += len(predicted - expected)
            counts['button_fn'] += len(expected - predicted)
            counts['button_tn'] += len(set(BUTTONS) - expected - predicted)
    times = sorted(r['elapsed_ms'] for r in records)
    def percentile(p):
        if not times:
            return None
        pos = (len(times)-1) * p
        low, high = math.floor(pos), math.ceil(pos)
        return times[low] + (times[high] - times[low]) * (pos-low)
    return {
        'counts': dict(counts), 'by_tile': tile_classes,
        'tile_accuracy': ratio(counts['correct_tiles'], counts['known_tiles']),
        'exact_hand_rate': ratio(counts['exact_hands'], counts['hand_frames']),
        'sequence_accuracy': None if not counts['sequence_slots'] else 1-ratio(counts['sequence_edits'], counts['sequence_slots']),
        'known_tile_rejection_rate': ratio(counts['known_rejections'], counts['known_tiles']),
        'button_false_positive_rate': ratio(counts['button_fp'], counts['button_fp']+counts['button_tn']),
        'button_recall': ratio(counts['button_tp'], counts['button_tp']+counts['button_fn']),
        'negative_button_frame_fp_rate': ratio(counts['negative_button_false_positives'], counts['negative_button_frames']),
        'latency_ms': {'p50': percentile(.5), 'p95': percentile(.95)},
    }


def evaluate(data, split, matcher, detector):
    import cv2
    import numpy as np
    records = []
    for sample in data['samples']:
        if sample['split'] != split or sample['status'] != 'reviewed':
            continue
        image = cv2.imdecode(np.fromfile(sample['_image_path'], np.uint8), cv2.IMREAD_COLOR)
        if image is None or [image.shape[1], image.shape[0]] != sample['size']:
            raise ValueError(f"{sample['id']}: unreadable image or incorrect dimensions")
        row = {'id': sample['id'], 'session_id': sample['session_id'], 'size': sample['size'],
               'theme': sample.get('theme', 'unknown')}
        def crop(ann):
            l,t,r,b = ann['roi']; w,h = sample['size']
            roi = image[int(t*h):int(b*h), int(l*w):int(r*w)]
            if not roi.size:
                raise ValueError(f"{sample['id']}: empty ROI")
            return roi
        start = time.perf_counter()
        hand = sample.get('hand')
        if hand and hand.get('tiles') is not None:
            results = matcher.recognize_hand_tiles(crop(hand), n_expected=None)
            row.update(expected_hand=hand['tiles'], predicted_hand=[t for t,c in results],
                       hand_confidences=[float(c) for t,c in results])
        buttons = sample.get('buttons')
        if buttons and buttons.get('visible') is not None:
            row.update(expected_buttons=buttons['visible'], predicted_buttons=detector.detect_buttons(crop(buttons)))
        row['elapsed_ms'] = (time.perf_counter()-start)*1000
        records.append(row)
    return records


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=ROOT/'datasets/real_game/manifest.json')
    parser.add_argument('--split', choices=('development','test'), default='test')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--no-file-log', action='store_true', help='Console-only logging for read-only/CI environments')
    parser.add_argument('--output', type=Path, default=ROOT/'debug_output/real_validation')
    args = parser.parse_args(argv)
    try:
        data = validate_manifest(args.manifest)
        selected = [s for s in data['samples'] if s['split']==args.split and s['status']=='reviewed']
        if args.check:
            print(f"VALID: {len(data['samples'])} samples; {len(selected)} reviewed in {args.split}")
            return 0
        if not selected:
            raise ValueError(f'No reviewed {args.split} samples. Collect and label unused sessions first.')
        if args.no_file_log:
            import logging
            import utils.log as log
            logger = logging.getLogger('real_dataset')
            logger.addHandler(logging.StreamHandler(sys.stderr))
            logger.setLevel(logging.WARNING)
            log._impl._logger, log._impl._setup_done = logger, True
        from vision.tiles import TileTemplateMatcher
        from vision.buttons import ButtonDetector
        matcher, detector = TileTemplateMatcher(), ButtonDetector()
        if args.no_file_log:
            for name in list(logging.Logger.manager.loggerDict):
                if name.startswith('airtest'):
                    logging.getLogger(name).setLevel(logging.WARNING)
        if not matcher.is_ready:
            raise ValueError('No tile templates loaded')
        if any((s.get('buttons') or {}).get('visible') is not None for s in selected):
            if any(b not in detector._cv_templates and b not in detector._air_templates for b in BUTTONS):
                raise ValueError('Button evaluation requires all seven button templates')
        records = evaluate(data, args.split, matcher, detector)
        import cv2
        import numpy as np
        report = {'schema_version': 1, 'generated_at': datetime.now(timezone.utc).isoformat(),
                  'split': args.split, 'independent_test': args.split=='test',
                  'acceptance_passed': None,
                  'manifest_sha256': hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
                  'scope': 'annotated hand/button ROIs; no full-pipeline or action success claim',
                  'dataset_samples': len(data['samples']),
                  'pending_samples': sum(s['status']=='pending' for s in data['samples']),
                  'runtime': {'python': sys.version, 'opencv': cv2.__version__, 'numpy': np.__version__},
                  'implementation_sha256': {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                      for name in ('vision/tiles.py','vision/buttons.py','scripts/validate_real_dataset.py')},
                  'template_sha256': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                      for directory in (ROOT/'vision/templates/tiles', ROOT/'templates')
                      for p in sorted(directory.glob('*.png'))},
                  'sessions': len({r['session_id'] for r in records}), 'samples': len(records),
                  'metrics': aggregate(records), 'records': records}
        report['by_resolution'] = {f'{w}x{h}': aggregate([r for r in records if r['size']==[w,h]])
                                   for w,h in sorted({tuple(r['size']) for r in records})}
        report['by_theme'] = {theme: aggregate([r for r in records if r['theme']==theme])
                              for theme in sorted({r['theme'] for r in records})}
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output/'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        lines = ['# Real screenshot validation', '', f'Split: {args.split}; samples: {len(records)}; sessions: {report["sessions"]}',
                 'Development results cannot be used as held-out acceptance.',
                 'Metrics use manually annotated ROIs, not automatic ROI detection or complete game actions.', '',
                 'White tile=31 and red tiles=34..36 require exact identity. Unknown/back=-1.',
                 'Tile accuracy counts annotated visible tiles; extras penalize exact-hand and sequence metrics.',
                 'Latency is annotated hand/button ROI processing (warm model), not screenshot/full-pipeline latency.', '']
        for key,value in report['metrics'].items():
            lines.append(f'- {key}: {json.dumps(value, ensure_ascii=False)}')
        (args.output/'REPORT.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
        print(json.dumps({k: report[k] for k in ('split','samples','sessions','metrics')}, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
