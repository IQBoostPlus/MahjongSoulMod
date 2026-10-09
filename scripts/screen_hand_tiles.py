"""Screen hand tiles in registered real-game screenshots for manual annotation.

For each manifest sample with a hand ROI this crops the ROI, splits it into
individual tiles with the same localizer the vision pipeline uses, predicts
each tile, and writes per-sample annotated ROI + contact sheets plus an
HTML report under debug_output/hand_screening/. No manifest labels are
written — the outputs are for the human reviewer to compare against the
original image and confirm the hand ROI placement.

Usage:
    python scripts/screen_hand_tiles.py
    python scripts/screen_hand_tiles.py --split development --ids shot-e58f1ed1d014
"""
import argparse
import base64
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

# Test-process-style log bypass: vision.tiles imports utils.log which writes to
# the user home dir; this script only needs console output.
import utils.log as _log_mod
_log_mod._impl._logger = logging.getLogger("screen_hand_tiles")
_log_mod._impl._logger.addHandler(logging.NullHandler())
_log_mod._impl._setup_done = True

from vision.tiles import TileRecognizer, TILE_NAMES  # noqa: E402


def decode_image(path):
    import cv2
    return cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)


def tile_name(tid):
    return TILE_NAMES[tid] if 0 <= tid < len(TILE_NAMES) else "?"


def png_b64(img):
    import cv2
    ok, buf = cv2.imencode('.png', img)
    if not ok:
        return ""
    return base64.b64encode(buf.tobytes()).decode('ascii')


def draw_roi(roi, boxes, n):
    """Annotated ROI copy: tile index + box for each located tile."""
    import cv2
    out = roi.copy()
    for i, (bx, by, bw, bh) in enumerate(boxes):
        cv2.rectangle(out, (bx, by), (bx + bw, by + bh), (0, 200, 0), 2)
        cv2.putText(out, str(i), (bx + 2, by + 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)
    cv2.putText(out, f"{n} tiles", (6, 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    return out


def draw_sheet(roi, boxes, preds):
    """Contact sheet: each tile crop side by side with index + prediction."""
    import cv2
    TILE_H = 140
    LABEL_H = 26
    GAP = 6
    PAD = 10
    widths = []
    strips = []
    for (bx, by, bw, bh), (tid, conf) in zip(boxes, preds):
        crop = roi[by:by + bh, bx:bx + bw]
        if crop.size == 0:
            widths.append(TILE_H // 2)
            strips.append(np.full((LABEL_H + TILE_H, TILE_H // 2, 3), 200, np.uint8))
            continue
        tw = max(24, int(TILE_H * bw / max(1, bh)))
        crop = cv2.resize(crop, (tw, TILE_H))
        widths.append(tw)
        label = f"{tile_name(tid)} {conf:.2f}" if tid >= 0 else "reject"
        strip = np.full((LABEL_H + TILE_H, tw, 3), 255, np.uint8)
        cv2.putText(strip, label, (2, LABEL_H - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        strip[LABEL_H:, :] = crop
        strips.append(strip)
    sheet_w = sum(widths) + GAP * (len(strips) - 1) + PAD * 2
    sheet = np.full((LABEL_H + TILE_H + PAD * 2, sheet_w, 3), 245, np.uint8)
    x = PAD
    for strip, tw in zip(strips, widths):
        sheet[PAD:PAD + strip.shape[0], x:x + tw] = strip
        x += tw + GAP
    return sheet


def draw_full_preview(image, w, h, l, t, r, b):
    """Downscaled full image with the hand ROI rectangle drawn on it."""
    import cv2
    scale = 900.0 / max(1, w)
    preview = cv2.resize(image, (int(w * scale), int(h * scale)))
    x1, y1 = int(l * w * scale), int(t * h * scale)
    x2, y2 = int(r * w * scale), int(b * h * scale)
    cv2.rectangle(preview, (x1, y1), (x2, y2), (0, 0, 255), 3)
    return preview


def screen(sample, matcher, out_dir):
    import cv2
    sid = sample['id']
    image = decode_image(ROOT / 'datasets' / 'real_game' / sample['image'])
    if image is None:
        print(f"[{sid}] unreadable image")
        return None
    w, h = sample['size']
    l, t, r, b = sample['hand']['roi']
    x1, y1 = int(l * w), int(t * h)
    x2, y2 = int(r * w), int(b * h)
    if x2 <= x1 or y2 <= y1:
        print(f"[{sid}] empty hand ROI")
        return None
    roi = image[y1:y2, x1:x2]

    results = matcher.recognize_hand(roi, n_expected=None)
    boxes = matcher.hand_boxes
    preds = [(tid, float(cf)) for tid, cf in results[:len(boxes)]]
    preds += [(-1, 0.0)] * (len(boxes) - len(preds))

    roi_png = draw_roi(roi, boxes, len(boxes))
    sheet_png = draw_sheet(roi, boxes, preds)
    full_png = draw_full_preview(image, w, h, l, t, r, b)
    cv2.imencode('.png', roi_png)[1].tofile(str(out_dir / f"{sid}_roi.png"))
    cv2.imencode('.png', sheet_png)[1].tofile(str(out_dir / f"{sid}_tiles.png"))
    cv2.imencode('.png', full_png)[1].tofile(str(out_dir / f"{sid}_full.png"))

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    tiles = []
    for i, ((bx, by, bw, bh), (p, c)) in enumerate(zip(boxes, preds)):
        crop = roi[by:by + bh, bx:bx + bw]
        tile_gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.size else gray[:0]
        tiles.append({
            'i': i, 'box': [bx, by, bw, bh], 'pred': p,
            'name': tile_name(p) if p >= 0 else None,
            'conf': round(c, 4),
            'mean': round(float(tile_gray.mean()), 1) if tile_gray.size else None,
            'std': round(float(tile_gray.std()), 1) if tile_gray.size else None,
        })

    entry = {
        'image': sample['image'], 'size': sample['size'],
        'status': sample['status'], 'roi': sample['hand']['roi'],
        'theme': sample.get('theme', 'unknown'),
        'labeled': sample['hand'].get('tiles'),
        'n_tiles': len(boxes),
        'roi_stats': {
            'mean': round(float(gray.mean()), 1),
            'std': round(float(gray.std()), 1),
            'bright_frac': round(float((gray > 150).mean()), 3),
        },
        'tiles': tiles,
    }
    names = " ".join(tile_name(p) for p, _ in preds)
    print(f"[{sid}] {sample['status']:<8} {len(boxes):>2} tiles  pred: {names}")
    return entry


def render_html(report, out_dir):
    sections = []
    for sid, e in report.items():
        tiles_html = "".join(
            f"<tr><td>{t['i']}</td><td>{t['name'] or '—'}</td>"
            f"<td>{t['conf']:.3f}</td><td>{t['mean']}</td><td>{t['std']}</td></tr>"
            for t in e['tiles'])
        labeled = e['labeled']
        labeled_html = (" ".join(tile_name(t) for t in labeled)
                        if isinstance(labeled, list) else f"<i>{labeled}</i>")
        pred_html = " ".join(t['name'] or "?" for t in e['tiles'])
        stats = e['roi_stats']
        sections.append(f"""
<h2>{sid} <small>({e['status']}, {e['size'][0]}x{e['size'][1]}, {e['theme']})</small></h2>
<p>ROI {e['roi']} — gray mean {stats['mean']}, std {stats['std']},
   bright frac {stats['bright_frac']} | 标注: {labeled_html} | 预测: {pred_html}</p>
<div class="row">
  <figure><img src="data:image/png;base64,{png_b64_from_file(out_dir / (sid + '_full.png'))}">
    <figcaption>整图 + 手牌 ROI 框 (复核 ROI 位置)</figcaption></figure>
  <figure><img src="data:image/png;base64,{png_b64_from_file(out_dir / (sid + '_roi.png'))}">
    <figcaption>ROI 裁剪 + 定位框 + 序号</figcaption></figure>
</div>
<img class="sheet" src="data:image/png;base64,{png_b64_from_file(out_dir / (sid + '_tiles.png'))}">
<table><tr><th>i</th><th>预测</th><th>conf</th><th>tile mean</th><th>tile std</th></tr>
{tiles_html}</table>
""")
    html = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>手牌筛选 — hand screening</title>
<style>
 body {{ font-family: sans-serif; max-width: 1500px; margin: 2em auto; padding: 0 1em; }}
 figure {{ display: inline-block; margin: 0 1em 1em 0; vertical-align: top; }}
 figcaption {{ font-size: 12px; color: #555; }}
 .row img {{ height: 260px; }}
 img.sheet {{ display: block; margin: 0.5em 0 1em; }}
 table {{ border-collapse: collapse; margin-bottom: 2em; }}
 td, th {{ border: 1px solid #ccc; padding: 2px 10px; font-size: 13px; }}
</style></head><body>
<h1>手牌筛选报告 — {len(report)} 张截图</h1>
<p>每张图: 整图(红框=manifest 手牌 ROI 初值, 需目视确认位置) + ROI 裁剪(绿框=定位框, 数字=序号)
 + 逐牌裁切(标签=识别预测, 仅供参照, 不作为真值)。请对照原图逐张筛选, 确认后回填 manifest
 hand.tiles / hand.roi / reviewer。</p>
{''.join(sections)}
</body></html>"""
    (out_dir / 'REPORT.html').write_text(html, encoding='utf-8')


def png_b64_from_file(path):
    return base64.b64encode(Path(path).read_bytes()).decode('ascii')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', default=str(ROOT / 'datasets' / 'real_game' / 'manifest.json'))
    parser.add_argument('--split', default='development')
    parser.add_argument('--ids', default=None, help='comma-separated sample ids; default: all')
    parser.add_argument('--out', default=str(ROOT / 'debug_output' / 'hand_screening'))
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    data = json.loads(Path(args.manifest).read_text(encoding='utf-8'))
    ids = set(args.ids.split(',')) if args.ids else None
    samples = [s for s in data['samples']
               if s['split'] == args.split and s.get('hand') and s['hand'].get('roi')
               and (ids is None or s['id'] in ids)]

    matcher = TileRecognizer()
    report = {}
    for sample in samples:
        entry = screen(sample, matcher, out_dir)
        if entry:
            report[sample['id']] = entry

    (out_dir / 'screening.json').write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    render_html(report, out_dir)
    print(f"\nWrote {len(report)} samples -> {out_dir}  (open REPORT.html)")


if __name__ == '__main__':
    main()
