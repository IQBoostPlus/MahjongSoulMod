# -*- coding: utf-8 -*-
"""
v2.5 牌面识别批量验证 (batch validation)

在只有有限真实截图的条件下, 分三层最大化验证覆盖面:
  A. 真实局端到端     — debug_output/1.png 走完整 recognize_hand_tiles, 对照人工 GT
  B. 真实单牌扰动鲁棒 — 从 1.png 精确裁出的真实牌, 做尺度/亮度/对比度/模糊/JPEG/深色反转
  C. 全牌型主题覆盖   — 37 张模板做原样/深色反转/放大, 覆盖真实局没出现的牌型

输出:
  - 控制台分花色 / 分扰动准确率 + 错例清单
  - debug_output/batch_validation/results.json   机器可读结果
  - debug_output/batch_validation/REPORT.md      汇总报告
  - debug_output/batch_validation/golden_tiles.png 黄金单牌拼图 (供人工核对)

用法:
  python scripts/batch_validate.py
"""
import os
import sys
import json
import time
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

OUT_DIR = os.path.join(ROOT, "debug_output", "batch_validation")
os.makedirs(OUT_DIR, exist_ok=True)

# 1.png 手牌从左到右人工标注 (3m,6m,8m,1p,2p,2p,9p,9p,2s,4s,6s,E,牌背,7m)
GT_1PNG = [2, 5, 7, 9, 10, 10, 17, 17, 19, 21, 23, 27, -1, 6]
HAND_RECT = (0.116, 0.817, 0.825, 0.954)

rng = np.random.default_rng(42)


def suit_of(tid):
    if tid < 0:
        return "back"
    if 0 <= tid <= 8:
        return "man(万)"
    if 9 <= tid <= 17:
        return "pin(筒)"
    if 18 <= tid <= 26:
        return "sou(索)"
    if 27 <= tid <= 33:
        return "ji(字)"
    return "red(赤)"


# ── 扰动函数 (输入输出均为 BGR 三通道或灰度, 模拟真实采集差异) ──
def perturb(img, kind, cv2):
    g = img
    if kind == "base":
        return g
    if kind.startswith("scale"):
        f = float(kind.split("@")[1])
        h, w = g.shape[:2]
        nh, nw = max(8, int(h * f)), max(8, int(w * f))
        interp = cv2.INTER_AREA if f < 1 else cv2.INTER_LINEAR
        return cv2.resize(g, (nw, nh), interpolation=interp)
    if kind.startswith("bright"):
        d = int(kind.split("@")[1])
        return np.clip(g.astype(np.int16) + d, 0, 255).astype(np.uint8)
    if kind.startswith("contrast"):
        f = float(kind.split("@")[1])
        return np.clip((g.astype(np.float32) - 128) * f + 128, 0, 255).astype(np.uint8)
    if kind == "blur3":
        return cv2.GaussianBlur(g, (3, 3), 0)
    if kind.startswith("jpeg"):
        q = int(kind.split("@")[1])
        ok, enc = cv2.imencode(".jpg", g, [cv2.IMWRITE_JPEG_QUALITY, q])
        return cv2.imdecode(enc, cv2.IMREAD_COLOR if g.ndim == 3 else cv2.IMREAD_GRAYSCALE)
    if kind == "invert":
        return cv2.bitwise_not(g)
    if kind == "noise":
        n = rng.normal(0, 6, g.shape).astype(np.int16)
        return np.clip(g.astype(np.int16) + n, 0, 255).astype(np.uint8)
    raise ValueError(kind)


PERTURBATIONS = [
    "base",
    "scale@0.70", "scale@0.85", "scale@1.15", "scale@1.30",
    "bright@-30", "bright@+30",
    "contrast@0.7", "contrast@1.3",
    "blur3", "jpeg@50", "noise", "invert",
]


def main():
    import cv2
    from vision.tiles import (TileTemplateMatcher, tile_to_name, TOTAL_TEMPLATES, RED_DORA_MAP)

    matcher = TileTemplateMatcher(invert_dark=True, margin_threshold=0.01)

    # 统计容器: layer -> kind/suit -> [correct, total]
    cases = []   # 每条: layer, group, gt, pred, conf, ms

    def record(layer, group, gt, pred, conf, ms):
        cases.append(dict(layer=layer, group=group, gt=gt, pred=pred,
                          conf=round(float(conf), 4), ms=round(ms, 2)))

    # ═══════════════ A. 真实局端到端 ═══════════════
    shot = cv2.imread(os.path.join(ROOT, "debug_output", "1.png"))
    H, W = shot.shape[:2]
    l, t, r, b = [int(v * s) for v, s in zip(HAND_RECT, [W, H, W, H])]
    hand = shot[t:b, l:r]
    t0 = time.perf_counter()
    res = matcher.recognize_hand_tiles(hand, n_expected=None)
    e2e_ms = (time.perf_counter() - t0) * 1000
    for i, (tid, conf) in enumerate(res):
        gt = GT_1PNG[i] if i < len(GT_1PNG) else -99
        record("A_real_frame", "e2e", gt, tid, conf, 0.0)

    # ═══════════════ B. 真实单牌扰动鲁棒 ═══════════════
    gray_hand = cv2.cvtColor(hand, cv2.COLOR_BGR2GRAY)
    boxes = matcher._locate_hand_tiles(gray_hand)
    golden = []  # (gt, bgr_crop)
    for i, (x, y, bw, bh) in enumerate(boxes):
        gt = GT_1PNG[i] if i < len(GT_1PNG) else -99
        golden.append((gt, hand[y:y + bh, x:x + bw]))

    # 导出黄金单牌拼图供人工核对
    pad = 4
    tiles_resized = [cv2.resize(c, (80, 129)) for _, c in golden]
    strip = np.full((129, len(tiles_resized) * (80 + pad) + pad, 3), 30, np.uint8)
    for k, tr in enumerate(tiles_resized):
        strip[:, pad + k * (80 + pad):pad + k * (80 + pad) + 80] = tr
    cv2.imwrite(os.path.join(OUT_DIR, "golden_tiles.png"), strip)

    for gt, crop in golden:
        for kind in PERTURBATIONS:
            p = perturb(crop, kind, cv2)
            t0 = time.perf_counter()
            pred, conf = matcher.match_single(p)
            ms = (time.perf_counter() - t0) * 1000
            if gt == -1:
                # 牌背: 期望拒识 (-1); invert 后仍是背面也应 -1
                record("B_real_tile_perturb", kind, -1, pred, conf, ms)
            else:
                record("B_real_tile_perturb", kind, gt, pred, conf, ms)

    # ═══════════════ C. 全牌型模板主题/尺度覆盖 ═══════════════
    tdir = os.path.join(ROOT, "vision", "templates", "tiles")
    for tid in range(TOTAL_TEMPLATES):
        tp = os.path.join(tdir, f"{tid}.png")
        if not os.path.isfile(tp):
            continue
        tmpl = cv2.imread(tp, cv2.IMREAD_GRAYSCALE)
        if tmpl is None:
            continue
        for kind in ["self", "invert", "scale@1.50"]:
            if kind == "self":
                q = tmpl
            elif kind == "invert":
                q = cv2.bitwise_not(tmpl)
            else:
                q = cv2.resize(tmpl, (int(80 * 1.5), int(129 * 1.5)),
                               interpolation=cv2.INTER_LINEAR)
            t0 = time.perf_counter()
            pred, conf = matcher.match_single(q)
            ms = (time.perf_counter() - t0) * 1000
            # 正确性: 白板(31)设计上即拒识(-1); 赤宝可判对应普通牌; 其余须精确命中
            if tid == 31:
                ok = (pred == -1)
            elif tid in RED_DORA_MAP:
                ok = pred in (tid, RED_DORA_MAP[tid])
            else:
                ok = (pred == tid)
            record("C_template_cover", kind, tid, pred, conf, ms)
            cases[-1]["correct"] = ok

    # ═══════════════ 汇总 ═══════════════
    def agg(subset, key):
        d = {}
        for c in subset:
            k = c[key]
            d.setdefault(k, [0, 0])
            d[k][1] += 1
            # C 层用预计算 correct; 其余 gt==pred (牌背 gt=-1 时 pred=-1 即正确)
            is_ok = c["correct"] if "correct" in c else (c["gt"] == c["pred"])
            d[k][0] += int(is_ok)
        return d

    report = {"layers": {}, "errors": [], "timing": {"e2e_ms": round(e2e_ms, 1)}}
    lines = ["# v2.5 牌面识别批量验证报告", "",
             f"- 生成时间(本地): {time.strftime('%Y-%m-%d %H:%M:%S')}",
             f"- A 真实局端到端耗时: {e2e_ms:.0f} ms", ""]

    layer_names = {
        "A_real_frame": "A. 真实局端到端 (1.png)",
        "B_real_tile_perturb": "B. 真实单牌 × 采集扰动",
        "C_template_cover": "C. 全牌型模板 × 主题/尺度",
    }
    grand_ok = grand_n = 0
    for layer, lname in layer_names.items():
        sub = [c for c in cases if c["layer"] == layer]
        by_group = agg(sub, "group")
        by_suit = agg(sub, "gt")
        # 汇总层内总数
        ok = sum(v[0] for v in by_group.values())
        n = sum(v[1] for v in by_group.values())
        grand_ok += ok
        grand_n += n
        report["layers"][layer] = {
            "accuracy": round(ok / max(1, n), 4), "correct": ok, "total": n,
            "by_group": {k: {"correct": v[0], "total": v[1],
                             "acc": round(v[0] / max(1, v[1]), 4)}
                         for k, v in sorted(by_group.items())},
        }
        lines += [f"## {lname}", "", f"**合计 {ok}/{n} = {ok/max(1,n)*100:.1f}%**", ""]
        if layer == "B_real_tile_perturb":
            lines += ["| 扰动 | 正确/总数 | 准确率 |", "|---|---|---|"]
            for k, v in sorted(by_group.items()):
                lines.append(f"| {k} | {v[0]}/{v[1]} | {v[0]/max(1,v[1])*100:.1f}% |")
            lines.append("")
        if layer == "C_template_cover":
            lines += ["| 变换 | 正确/总数 | 准确率 |", "|---|---|---|"]
            for k, v in sorted(by_group.items()):
                lines.append(f"| {k} | {v[0]}/{v[1]} | {v[0]/max(1,v[1])*100:.1f}% |")
            lines.append("")
        # 分花色 (仅 B/C 有意义)
        if layer in ("B_real_tile_perturb", "C_template_cover"):
            sd = {}
            for c in sub:
                s = suit_of(c["gt"])
                sd.setdefault(s, [0, 0])
                sd[s][1] += 1
                is_ok = c["correct"] if "correct" in c else c["gt"] == c["pred"]
                sd[s][0] += int(is_ok)
            lines += ["| 花色 | 正确/总数 | 准确率 |", "|---|---|---|"]
            for s, v in sorted(sd.items()):
                lines.append(f"| {s} | {v[0]}/{v[1]} | {v[0]/max(1,v[1])*100:.1f}% |")
            lines.append("")
        # 错例
        errs = []
        for c in sub:
            is_ok = c["correct"] if "correct" in c else c["gt"] == c["pred"]
            if not is_ok:
                errs.append(c)
                report["errors"].append(c)
        if errs:
            lines += [f"### 错例 ({len(errs)})", "",
                      "| 组 | 真实 | 识别为 | 置信度 | 耗时ms |", "|---|---|---|---|---|"]
            for c in errs[:60]:
                gn = "牌背" if c["gt"] < 0 else tile_to_name(c["gt"])
                pn = "拒识" if c["pred"] < 0 else tile_to_name(c["pred"])
                lines.append(f"| {c['group']} | {gn} | {pn} | {c['conf']:.3f} | {c['ms']:.1f} |")
            lines.append("")

    # B 层单张平均耗时
    b_ms = [c["ms"] for c in cases if c["layer"] == "B_real_tile_perturb" and c["ms"] > 0]
    avg_ms = float(np.mean(b_ms)) if b_ms else 0.0
    report["timing"]["avg_single_ms"] = round(avg_ms, 1)

    lines += ["---", "",
              f"## 总样本: {grand_ok}/{grand_n} = {grand_ok/max(1,grand_n)*100:.1f}%",
              f"- B 层单张平均耗时: {avg_ms:.1f} ms",
              "- 注: B/C 层为真实单牌/模板的合成扰动, 用于测鲁棒性与全牌型下限;",
              "  真实多局泛化仍需补充更多对局截图。", "",
              "> 说明1: C 层白板(31)无特征, 正确预期就是拒识(-1), 已计为正确;",
              "> 说明2: v2.5 加固——深色反转时 SIFT 改在同主题(浅色)图上提特征; SIFT 失败时 CCOEFF 需>=0.55 才采信;",
              "  深色反转丢失红色, 赤宝回落普通牌。早期 invert 万子混淆/强噪声牌背误识/反转五万误判赤宝均已修复。",
              "> 局限: B/C 为合成扰动, 覆盖鲁棒性与全牌型下限; 真实多局/多分辨率/多主题泛化仍需补充对局截图。", ""]
    report["overall"] = {"correct": grand_ok, "total": grand_n,
                         "acc": round(grand_ok / max(1, grand_n), 4)}

    with open(os.path.join(OUT_DIR, "results.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    with open(os.path.join(OUT_DIR, "REPORT.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    # 控制台简报
    print("\n".join(lines))
    print(f"\n[written] {OUT_DIR}")


if __name__ == "__main__":
    main()
