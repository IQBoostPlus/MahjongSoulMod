"""Import screenshots or capture one explicitly named, active game window.

Collection never clicks, launches a game or infers labels. Each sample starts
pending; a human must fill hand/buttons and reviewer before evaluation.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def add_image(manifest, image, session, split, provenance, used_for_tuning=False,
              source_kind='local_capture', frame_index=0):
    from PIL import Image
    from scripts.validate_real_dataset import validate_manifest
    if (not session.strip() or not provenance.strip() or split not in ('development', 'test')
            or source_kind not in ('local_capture', 'external_unknown')):
        raise ValueError('Valid session, provenance, split and source kind are required')
    manifest = Path(manifest).resolve()
    manifest.parent.mkdir(parents=True, exist_ok=True)
    if manifest.exists():
        validate_manifest(manifest)
        data = json.loads(manifest.read_text(encoding='utf-8'))
    else:
        data = {'schema_version': 1, 'samples': []}
    if any(s['session_id']==session and s['split']!=split for s in data['samples']):
        raise ValueError('A session cannot cross development/test splits')
    if split=='test' and (used_for_tuning or source_kind!='local_capture'):
        raise ValueError('Test requires previously unused, known local captures')
    digest = hashlib.sha256(Path(image).read_bytes()).hexdigest()
    if any(s['sha256']==digest for s in data['samples']):
        raise ValueError('Duplicate image: already present in manifest')
    with Image.open(image) as shot:
        size = list(shot.size)
        shot.verify()
    sid = 'shot-' + uuid.uuid4().hex[:12]
    target = manifest.parent/'images'/f'{sid}{Path(image).suffix.lower()}'
    target.parent.mkdir(exist_ok=True)
    shutil.copyfile(image, target)
    from vision.regions import ROIDefinition
    regions = ROIDefinition()
    def roi(rect):
        return [rect.left,rect.top,rect.right,rect.bottom]
    sample = {'id': sid, 'session_id': session, 'split': split, 'status': 'pending',
              'source': {'kind': source_kind, 'provenance': provenance,
                         'used_for_tuning': used_for_tuning},
              'image': target.relative_to(manifest.parent).as_posix(), 'sha256': digest,
              'size': size, 'theme': 'unknown', 'frame_index': frame_index,
              'imported_at': datetime.now(timezone.utc).isoformat(),
              'hand': {'roi': roi(regions.hand), 'tiles': None},
              'buttons': {'roi': roi(regions.buttons), 'visible': None}, 'reviewer': None}
    data['samples'].append(sample)
    temporary = manifest.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    temporary.replace(manifest)
    return sid


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--image', type=Path, nargs='+')
    mode.add_argument('--capture-window', help='Exact title of an active, visible game window')
    parser.add_argument('--manifest', type=Path, default=ROOT/'datasets/real_game/manifest.json')
    parser.add_argument('--session-id', required=True, help='One actual game/session, not one ID per frame')
    parser.add_argument('--split', choices=('development','test'), default='development')
    parser.add_argument('--provenance', required=True, help='Actual source/capture conditions; do not invent origin')
    parser.add_argument('--used-for-tuning', action='store_true')
    parser.add_argument('--source-kind', choices=('local_capture','external_unknown'), default='local_capture')
    parser.add_argument('--count', type=int, default=1)
    parser.add_argument('--interval', type=float, default=2)
    args = parser.parse_args(argv)
    if not args.session_id.strip() or not args.provenance.strip() or not 1<=args.count<=500 or args.interval<1:
        parser.error('Nonempty session/provenance, count 1..500 and interval >=1 required')
    if args.split=='test' and (args.used_for_tuning or args.source_kind!='local_capture'):
        parser.error('Test requires unused local captures')
    try:
        if args.image:
            for index, source in enumerate(args.image):
                print(add_image(args.manifest, source, args.session_id, args.split,
                                args.provenance, args.used_for_tuning, args.source_kind, index))
        else:
            from PIL import ImageGrab
            import pygetwindow as gw
            import tempfile
            for index in range(args.count):
                matches = [w for w in gw.getAllWindows() if w.title==args.capture_window
                           and w.visible and not w.isMinimized and w.isActive]
                if len(matches)!=1:
                    raise ValueError('Exactly one visible, active window must match the exact title')
                window = matches[0]
                if window.width<=0 or window.height<=0:
                    raise ValueError('Invalid window dimensions')
                rect = (window.left,window.top,window.left+window.width,window.top+window.height)
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp)/'capture.png'
                    ImageGrab.grab(bbox=rect, all_screens=True).save(path)
                    if not window.isActive:
                        raise ValueError('Window lost focus during capture; discarded screenshot')
                    try:
                        print(add_image(args.manifest, path, args.session_id, args.split,
                                        args.provenance, args.used_for_tuning, 'local_capture', index))
                    except ValueError as exc:
                        if str(exc).startswith('Duplicate image'):
                            print('Skipped unchanged screenshot')
                        else:
                            raise
                if index+1<args.count:
                    time.sleep(args.interval)
        return 0
    except (OSError, ValueError, ImportError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
