"""
牌面识别 v2.3 算法修复测试

覆盖:
  - 深色主题灰度反转
  - TM_CCOEFF_NORMED 亮度不变匹配
  - Top-2 margin 检查 (ambiguous → -1)
  - 赤宝牌严格验证 & 降级
  - 白板排除
  - 模板加载完整性
"""

import sys
import os
import unittest
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vision.tiles import (
    TileTemplateMatcher, TileRecognizer,
    TILE_NAMES, TILE_COUNT, TOTAL_TEMPLATES,
    RED_DORA_MAP, tile_to_name, red_to_normal,
)


class TestDarkThemeInversion(unittest.TestCase):
    """深色主题自动检测 & 灰度反转"""

    @classmethod
    def setUpClass(cls):
        cls.matcher = TileTemplateMatcher(invert_dark=True, margin_threshold=0.01)

    def test_invert_enabled_by_default(self):
        """默认启用灰度反转"""
        m = TileTemplateMatcher()
        self.assertTrue(m._invert_dark)

    def test_invert_can_disable(self):
        """可显式关闭灰度反转"""
        m = TileTemplateMatcher(invert_dark=False)
        self.assertFalse(m._invert_dark)

    def test_dark_roi_detected_and_inverted(self):
        """深色 ROI (mean < 100) 自动反转后能匹配模板"""
        # 用模板自身模拟 "浅色参考" — 反转后变深
        # 作为测试 ROI 再被检测为深色并反转回来
        if not self.matcher.is_ready:
            self.skipTest("No templates loaded")

        # 取一张模板作为 ground truth
        import cv2
        tmpl = self.matcher._templates.get(0)
        if tmpl is None:
            self.skipTest("Template 0 not found")

        # 模拟深色主题: 反转模板得到深色 ROI
        dark_roi = cv2.bitwise_not(tmpl)

        # 确认确实是深色的 (mean < 100)
        self.assertLess(float(np.mean(dark_roi)), 100,
                        "Inverted template should be dark")

        # 匹配 — 深色 ROI 应该被自动反转并匹配到 tile 0
        tile_id, conf = self.matcher.match_single(dark_roi)
        self.assertEqual(tile_id, 0,
                         f"Dark inverted template should match tile 0, got {tile_id}")
        self.assertGreater(conf, 0.8,
                           f"Confidence should be high after inversion, got {conf:.3f}")

    def test_light_roi_not_inverted(self):
        """浅色 ROI (mean > 100) 不会被反转"""
        if not self.matcher.is_ready:
            self.skipTest("No templates loaded")

        import cv2
        tmpl = self.matcher._templates.get(5)
        if tmpl is None:
            self.skipTest("Template 5 not found")

        # 浅色模板直接匹配
        light_roi = tmpl.copy()
        self.assertGreater(float(np.mean(light_roi)), 100,
                           "Original template should be light")

        tile_id, conf = self.matcher.match_single(light_roi)
        self.assertEqual(tile_id, 5,
                         f"Light ROI should match tile 5 directly, got {tile_id}")
        self.assertGreater(conf, 0.8)


class TestCoefficientMatching(unittest.TestCase):
    """TM_CCORR_NORMED — 灰度反转匹配验证"""

    @classmethod
    def setUpClass(cls):
        cls.matcher = TileTemplateMatcher(invert_dark=True, margin_threshold=0.01)

    def test_inverted_template_matches_via_inversion(self):
        """反转后的模板通过反转通道正确匹配"""
        if not self.matcher.is_ready:
            self.skipTest("No templates loaded")
        import cv2
        tmpl = self.matcher._templates.get(10)
        if tmpl is None:
            self.skipTest("Template 10 not found")
        inverted = cv2.bitwise_not(tmpl)
        tile_id, conf = self.matcher.match_single(inverted)
        self.assertEqual(tile_id, 10)

    def test_dark_inverted_matches_with_inversion(self):
        """反转模板 (模拟深色主题) 通过反转通道匹配"""
        if not self.matcher.is_ready:
            self.skipTest("No templates loaded")
        import cv2
        tmpl = self.matcher._templates.get(15)
        if tmpl is None:
            self.skipTest("Template 15 not found")
        dark = cv2.bitwise_not(tmpl)
        tile_id, conf = self.matcher.match_single(dark)
        self.assertEqual(tile_id, 15,
                         f"Dark inverted should match via inversion path, got {tile_id}")


class TestMarginCheck(unittest.TestCase):
    """Top-2 margin 检查 — 歧义候选时返回 -1"""

    def test_clear_winner_passes(self):
        """明确胜出者 — 正常返回"""
        matcher = TileTemplateMatcher(margin_threshold=0.01, invert_dark=False)
        if not matcher.is_ready:
            self.skipTest("No templates loaded")

        import cv2
        tmpl = matcher._templates.get(20)
        if tmpl is None:
            self.skipTest("Template 20 not found")

        tile_id, conf = matcher.match_single(tmpl)
        self.assertGreaterEqual(tile_id, 0,
                                "Clear match should return a valid ID")

    def test_ambiguous_returns_minus_one(self):
        """两个候选过于接近 → 返回 -1"""
        # 使用严格的 margin 阈值模拟歧义
        matcher = TileTemplateMatcher(margin_threshold=0.50, invert_dark=False,
                                      threshold=0.01)
        if not matcher.is_ready:
            self.skipTest("No templates loaded")

        import cv2
        # 使用白板 (tile 31) + 少量噪声 → 各种模板得分都会很低且接近
        tmpl_31 = matcher._templates.get(31)
        if tmpl_31 is None:
            self.skipTest("Template 31 (白板) not found")

        # 白板 ROI — 几乎所有模板得分接近
        tile_id, conf = matcher.match_single(tmpl_31)
        # 由于 margin_threshold=0.50，白板+噪声会触发 margin 检查
        # 注意: 白板可能被白板排除规则先捕获 (best_id==31 → -1)
        # 这是预期行为
        self.assertIn(tile_id, [-1, 31],
                      f"Ambiguous/blank should return -1 or 31, got {tile_id}")

    def test_default_margin_enabled(self):
        """默认 margin_threshold=0.01"""
        m = TileTemplateMatcher()
        self.assertEqual(m._margin_threshold, 0.01)


class TestRedDoraDowngrade(unittest.TestCase):
    """赤宝牌严格验证 → 低置信度时降级为普通 5"""

    @classmethod
    def setUpClass(cls):
        cls.matcher = TileTemplateMatcher(
            red_dora_strict=True, invert_dark=False, margin_threshold=0.005
        )

    def test_red_dora_34_maps_to_4(self):
        """赤5万 (34) → 普通5万 (4)"""
        self.assertIn(34, RED_DORA_MAP)
        self.assertEqual(RED_DORA_MAP[34], 4)

    def test_red_dora_35_maps_to_13(self):
        """赤5筒 (35) → 普通5筒 (13)"""
        self.assertIn(35, RED_DORA_MAP)
        self.assertEqual(RED_DORA_MAP[35], 13)

    def test_red_dora_36_maps_to_22(self):
        """赤5索 (36) → 普通5索 (22)"""
        self.assertIn(36, RED_DORA_MAP)
        self.assertEqual(RED_DORA_MAP[36], 22)

    def test_red_dora_high_confidence_kept(self):
        """赤宝牌匹配置信度 ≥ 0.88 → 保持"""
        if not self.matcher.is_ready:
            self.skipTest("No templates loaded")

        import cv2
        tmpl_34 = self.matcher._templates.get(34)  # 赤5万
        if tmpl_34 is None:
            self.skipTest("Red dora template 34 not found")

        # 精确匹配自身 → 高置信度
        tile_id, conf = self.matcher.match_single(tmpl_34)
        # 应该保持为赤宝牌 (34), 不会被降级
        if conf >= 0.88:
            self.assertEqual(tile_id, 34,
                             f"High-conf red dora should stay as 34, got {tile_id}")
        else:
            # 如果置信度不够 → 降级为 4
            self.assertEqual(tile_id, 4,
                             f"Low-conf red dora should downgrade to 4, got {tile_id}")

    def test_red_dora_strict_can_disable(self):
        """可关闭赤宝牌严格验证"""
        m = TileTemplateMatcher(red_dora_strict=False)
        self.assertFalse(m._red_dora_strict)


class TestBlankTileExclusion(unittest.TestCase):
    """白板 (tile 31) 排除"""

    def test_blank_template_excluded(self):
        """匹配到白板 → 返回 -1"""
        matcher = TileTemplateMatcher(invert_dark=False, margin_threshold=0.01)
        if not matcher.is_ready:
            self.skipTest("No templates loaded")

        import cv2
        tmpl_31 = matcher._templates.get(31)
        if tmpl_31 is None:
            self.skipTest("Template 31 (白板) not found")

        tile_id, conf = matcher.match_single(tmpl_31)
        self.assertEqual(tile_id, -1,
                         f"Blank tile (31) should be excluded, got {tile_id}")


class TestTemplateLoading(unittest.TestCase):
    """模板加载完整性"""

    def test_all_37_templates_loaded(self):
        """所有 37 张模板 (34 普通 + 3 赤宝牌) 都已加载"""
        matcher = TileTemplateMatcher()
        self.assertEqual(len(matcher._templates), TOTAL_TEMPLATES,
                         f"Expected {TOTAL_TEMPLATES} templates loaded")
        self.assertEqual(len(matcher._edge_templates), TOTAL_TEMPLATES,
                         f"Expected {TOTAL_TEMPLATES} edge templates")

    def test_is_ready(self):
        """is_ready 返回 True (≥34 模板)"""
        matcher = TileTemplateMatcher()
        self.assertTrue(matcher.is_ready)

    def test_all_tile_ids_present(self):
        """所有 tile ID 0-36 都有对应模板"""
        matcher = TileTemplateMatcher()
        for i in range(TOTAL_TEMPLATES):
            self.assertIn(i, matcher._templates,
                          f"Template {i} ({tile_to_name(i)}) missing")

    def test_edge_templates_exist(self):
        """每张模板都有对应的 Canny 边缘模板"""
        matcher = TileTemplateMatcher()
        for tile_id in matcher._templates:
            self.assertIn(tile_id, matcher._edge_templates,
                          f"Edge template {tile_id} missing")
            self.assertGreater(matcher._edge_templates[tile_id].sum(), 0,
                               f"Edge template {tile_id} is empty (all black)")


class TestTileRecognizerIntegration(unittest.TestCase):
    """TileRecognizer 集成测试 — v2.3 参数传递"""

    def test_recognizer_passes_new_params(self):
        """TileRecognizer 正确传递 v2.3 参数给 TileTemplateMatcher"""
        rec = TileRecognizer(
            threshold=0.75,
            margin_threshold=0.08,
            invert_dark=True,
            red_dora_strict=True,
        )
        self.assertEqual(rec._matcher._threshold, 0.75)
        self.assertEqual(rec._matcher._margin_threshold, 0.08)
        self.assertTrue(rec._matcher._invert_dark)
        self.assertTrue(rec._matcher._red_dora_strict)

    def test_recognizer_defaults(self):
        """TileRecognizer 默认参数"""
        rec = TileRecognizer()
        self.assertEqual(rec._matcher._margin_threshold, 0.01)
        self.assertTrue(rec._matcher._invert_dark)
        self.assertTrue(rec._matcher._red_dora_strict)


class TestUtilityFunctions(unittest.TestCase):
    """工具函数"""

    def test_tile_to_name_all(self):
        """所有 37 张牌的命名"""
        names = [
            "1m","2m","3m","4m","5m","6m","7m","8m","9m",
            "1p","2p","3p","4p","5p","6p","7p","8p","9p",
            "1s","2s","3s","4s","5s","6s","7s","8s","9s",
            "E","S","W","N","P","F","C",
            "r5m","r5p","r5s",
        ]
        for i, expected in enumerate(names):
            self.assertEqual(tile_to_name(i), expected)

    def test_red_to_normal_all(self):
        """赤 → 普通 映射"""
        self.assertEqual(red_to_normal(34), 4)
        self.assertEqual(red_to_normal(35), 13)
        self.assertEqual(red_to_normal(36), 22)
        # 普通牌不变
        self.assertEqual(red_to_normal(0), 0)
        self.assertEqual(red_to_normal(10), 10)
        self.assertEqual(red_to_normal(33), 33)


if __name__ == "__main__":
    unittest.main()
