"""
ROI 区域定义

雀魂游戏窗口内各功能区域的归一化坐标 (0.0 ~ 1.0, 相对窗口宽高)。
支持预置分辨率布局 + 按比例插值回退。

布局示意 (1920×1080 横屏, 自家在下):

┌─────────────────────────────────────────────────────────┐
│   [info]  场风/局数/供托                          (0.00-0.06 H) │
│                                                         │
│   ┌── 对手(左)牌河 ──┐              ┌── 对手(右)牌河 ──┐   │
│   │  (0.02-0.18 W)   │              │  (0.82-0.98 W)   │   │
│   └──────────────────┘              └──────────────────┘   │
│                                                         │
│   [dora] 宝牌指示牌                       (0.42-0.58 W, 0.22-0.28 H) │
│                                                         │
│   ┌── 上家牌河 ──┐                        ┌── 下家牌河 ──┐│
│   │ (0.02-0.18 W)│                        │(0.82-0.98 W) ││
│   └──────────────┘                        └──────────────┘│
│                                                         │
│   [buttons] 鸣牌按钮区                          (0.78-0.92 H) │
│                                                         │
│   [hand] 手牌区                                  (0.88-0.98 H) │
│   [draw]   摸牌区 (右手牌右侧)                            │
└─────────────────────────────────────────────────────────┘

竖屏布局 (移动端 9:16) 类似但旋转90° — 手牌在右, 对手在上方。
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field


# ═══════════════════════════════════════════════════════════════
#  Geometry primitives
# ═══════════════════════════════════════════════════════════════

@dataclass
class Rect:
    """归一化矩形 (0.0 ~ 1.0, 相对窗口尺寸)"""
    left: float
    top: float
    right: float
    bottom: float

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def center(self) -> Tuple[float, float]:
        return ((self.left + self.right) / 2, (self.top + self.bottom) / 2)

    def to_pixels(self, win_w: int, win_h: int) -> Tuple[int, int, int, int]:
        """转换为绝对像素坐标 (left, top, right, bottom)"""
        return (
            int(self.left * win_w),
            int(self.top * win_h),
            int(self.right * win_w),
            int(self.bottom * win_h),
        )

    def to_xywh(self, win_w: int, win_h: int) -> Tuple[int, int, int, int]:
        """转换为 (x, y, width, height) 绝对像素"""
        l, t, r, b = self.to_pixels(win_w, win_h)
        return (l, t, r - l, b - t)

    def crop(self, frame, win_w: int = None, win_h: int = None):
        """从截图裁切该区域"""
        if win_w is None:
            win_h, win_w = frame.shape[:2]
        l, t, r, b = self.to_pixels(win_w, win_h)
        # 边界保护
        h, w = frame.shape[:2]
        l = max(0, min(l, w - 1))
        t = max(0, min(t, h - 1))
        r = max(l + 1, min(r, w))
        b = max(t + 1, min(b, h))
        return frame[t:b, l:r]

    def scale(self, sx: float, sy: float) -> "Rect":
        """按比例缩放 (中心不变)"""
        cx, cy = self.center
        hw, hh = self.width * sx / 2, self.height * sy / 2
        return Rect(cx - hw, cy - hh, cx + hw, cy + hh)


# ═══════════════════════════════════════════════════════════════
#  ROI 定义
# ═══════════════════════════════════════════════════════════════

@dataclass
class ROIDefinition:
    """
    一个分辨率 / 布局的完整 ROI 定义。
    所有值均为归一化坐标 (0.0 ~ 1.0)。
    """
    # 窗口尺寸 (用于选择和验证)
    ref_width: int = 1920
    ref_height: int = 1080
    orientation: str = "landscape"  # "landscape" | "portrait"

    # 手牌区域 (紫色标注: 11.6-82.5%W, 81.7-95.4%H)
    hand: Rect = field(default_factory=lambda: Rect(0.116, 0.817, 0.825, 0.954))

    # 摸牌区域 (手牌右侧额外一张)
    draw_tile: Rect = field(default_factory=lambda: Rect(0.825, 0.817, 0.960, 0.954))

    # 4 家牌河 (绿色大框内部: 18.3-82.2%W, 13.5-76.2%H)
    discards: List[Rect] = field(default_factory=lambda: [
        Rect(0.183, 0.587, 0.822, 0.762),   # 0: 自家 (下半区)
        Rect(0.822, 0.135, 0.960, 0.587),   # 1: 下家 (右半区)
        Rect(0.183, 0.135, 0.822, 0.310),   # 2: 对家 (上半区)
        Rect(0.040, 0.135, 0.183, 0.587),   # 3: 上家 (左半区)
    ])

    # 4 家副露区域
    melds: List[Rect] = field(default_factory=lambda: [
        Rect(0.116, 0.840, 0.825, 0.950),   # 0: 自家
        Rect(0.750, 0.160, 0.830, 0.560),   # 1: 下家
        Rect(0.200, 0.160, 0.825, 0.300),   # 2: 对家
        Rect(0.170, 0.160, 0.250, 0.560),   # 3: 上家
    ])

    # 宝牌指示牌区域
    dora: Rect = field(default_factory=lambda: Rect(0.008, 0.058, 0.169, 0.163))

    # 鸣牌按钮区域 (黄色标注: 28.7-87.7%W, 53.1-79.2%H)
    buttons: Rect = field(default_factory=lambda: Rect(0.287, 0.531, 0.877, 0.792))

    # 信息栏 (场风/局数/供托/立直棒)
    info: Rect = field(default_factory=lambda: Rect(0.02, 0.00, 0.98, 0.06))

    # 各家分数 / 风位显示
    score_areas: List[Rect] = field(default_factory=lambda: [
        Rect(0.02, 0.00, 0.10, 0.06),   # 自家风位
        Rect(0.90, 0.06, 0.98, 0.12),   # 下家
        Rect(0.44, 0.00, 0.56, 0.06),   # 对家
        Rect(0.02, 0.06, 0.10, 0.12),   # 上家
    ])

    def get_discard_rect(self, seat: int) -> Rect:
        """获取指定座位的牌河区域"""
        if 0 <= seat < len(self.discards):
            return self.discards[seat]
        return self.discards[0]

    def get_meld_rect(self, seat: int) -> Rect:
        """获取指定座位的副露区域"""
        if 0 <= seat < len(self.melds):
            return self.melds[seat]
        return self.melds[0]


# ═══════════════════════════════════════════════════════════════
#  预置布局
# ═══════════════════════════════════════════════════════════════

# 横屏通用 (1920×1080, 2560×1440, 3840×2160 按比例缩放)
LANDSCAPE_DEFAULT = ROIDefinition(
    ref_width=1920, ref_height=1080, orientation="landscape",
)

REGION_PRESETS: Dict[str, ROIDefinition] = {
    "landscape_1080p": LANDSCAPE_DEFAULT,
    "landscape_1440p": ROIDefinition(
        ref_width=2560, ref_height=1440, orientation="landscape",
    ),
    "landscape_4k": ROIDefinition(
        ref_width=3840, ref_height=2160, orientation="landscape",
    ),
}


# ═══════════════════════════════════════════════════════════════
#  RegionConfig — 布局选择与自适应
# ═══════════════════════════════════════════════════════════════

class RegionConfig:
    """
    ROI 布局配置管理器。

    根据窗口 / 屏幕分辨率自动选择最佳 ROI 定义。
    未匹配到精确预设时, 按最近参考分辨率线性插值。

    用法:
        regions = RegionConfig.get_for_window(1920, 1080)
        hand_crop = regions.hand.crop(frame, win_w=1920, win_h=1080)
    """

    @staticmethod
    def get_for_window(width: int, height: int) -> ROIDefinition:
        """
        根据窗口尺寸返回最佳 ROI 定义。

        策略:
          1. 精确匹配预置
          2. 按最接近的预置等比例缩放
          3. 回退横屏/竖屏默认
        """
        # 精确匹配
        key = f"{width}x{height}"
        for preset_name, roi in REGION_PRESETS.items():
            if roi.ref_width == width and roi.ref_height == height:
                return roi

        # 找最接近参考分辨率 (按欧氏距离)
        best = None
        best_dist = float("inf")
        for preset_name, roi in REGION_PRESETS.items():
            dw = roi.ref_width - width
            dh = roi.ref_height - height
            dist = dw * dw + dh * dh
            if dist < best_dist:
                best_dist = dist
                best = roi

        if best is None:
            return LANDSCAPE_DEFAULT

        # 等比例缩放
        sx = width / best.ref_width
        sy = height / best.ref_height
        return RegionConfig._scale_roi(best, sx, sy)

    @staticmethod
    def get_for_screen(width: int, height: int) -> ROIDefinition:
        """同 get_for_window (全屏场景)"""
        return RegionConfig.get_for_window(width, height)

    @staticmethod
    def _scale_roi(roi: ROIDefinition, sx: float, sy: float) -> ROIDefinition:
        """按比例缩放 ROI 定义"""
        return ROIDefinition(
            ref_width=int(roi.ref_width * sx),
            ref_height=int(roi.ref_height * sy),
            orientation=roi.orientation,
            hand=roi.hand.scale(sx, sy),
            draw_tile=roi.draw_tile.scale(sx, sy),
            discards=[r.scale(sx, sy) for r in roi.discards],
            melds=[r.scale(sx, sy) for r in roi.melds],
            dora=roi.dora.scale(sx, sy),
            buttons=roi.buttons.scale(sx, sy),
            info=roi.info.scale(sx, sy),
            score_areas=[r.scale(sx, sy) for r in roi.score_areas],
        )
