"""
Vision Pipeline — 视觉管线编排

将采集、区域分割、识别串联, 每帧输出一个 VisionFrame。

流程:
  Capture → ROI Extract → Recognize (hand/river/dora/meld/button) → VisionFrame

用法:
    from vision.capture import CaptureFactory, CaptureConfig, CaptureBackend
    from vision.regions import RegionConfig
    from vision.pipeline import VisionPipeline

    capture = CaptureFactory.create(CaptureConfig())
    regions = RegionConfig.get_for_window(1920, 1080)
    pipeline = VisionPipeline(capture, regions)
    frame = pipeline.process_frame()
    print(frame.hand_tiles)
"""

import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

import numpy as np

from utils.log import Logger


# ═══════════════════════════════════════════════════════════════
#  Data structures
# ═══════════════════════════════════════════════════════════════

@dataclass
class MeldInfo:
    """副露信息"""
    tiles: List[int] = field(default_factory=list)
    meld_type: str = ""  # "chi", "pon", "kan_ming", "kan_an", "kan_jia"
    called_from: int = -1  # 来源座位


@dataclass
class RoundInfo:
    """局况信息 (从屏幕信息栏读取)"""
    round_wind: int = 0      # 0=东, 1=南
    round_number: int = 0    # 0-3
    honba: int = 0           # 本场数
    deposits: int = 0        # 供托 (立直棒)
    dealer: int = 0          # 庄家座位


@dataclass
class VisionFrame:
    """
    单帧的完整视觉识别结果。

    这是 VisionPipeline 的输出 — 一帧画面的全部语义信息。
    后续 StateDiffer 比较连续帧来推断游戏事件。
    """
    # 元信息
    timestamp: float = 0.0
    window_rect: Tuple[int, int, int, int] = (0, 0, 1920, 1080)  # (x, y, w, h)

    # 手牌 (tile_id 列表, 从左到右, 含刚摸的牌)
    hand_tiles: List[int] = field(default_factory=list)
    hand_confidences: List[float] = field(default_factory=list)

    # 牌河 (4 家, 每家是二维列表: 行×列)
    # seat 0=自家, 1=下家, 2=对家, 3=上家
    discards: List[List[int]] = field(default_factory=lambda: [[], [], [], []])

    # 副露 (4 家)
    melds: List[List[MeldInfo]] = field(default_factory=lambda: [[], [], [], []])

    # 宝牌指示牌
    dora_indicators: List[int] = field(default_factory=list)

    # 摸牌区 (刚摸到的那张牌, None=无)
    draw_tile: Optional[int] = None

    # 可见的鸣牌按钮
    visible_buttons: List[str] = field(default_factory=list)

    # 立直棒/供托 (从屏幕元素推断)
    riichi_sticks: int = 0

    # 局况
    round_info: Optional[RoundInfo] = None

    # 识别质量
    hand_confidence_avg: float = 0.0

    @property
    def hand_count(self) -> int:
        return len(self.hand_tiles)

    @property
    def win_w(self) -> int:
        return self.window_rect[2]

    @property
    def win_h(self) -> int:
        return self.window_rect[3]

    def get_flat_discards(self, seat: int) -> List[int]:
        """获取指定座位牌河的展平列表 (所有牌按舍出顺序)"""
        if 0 <= seat < len(self.discards):
            return self.discards[seat]
        return []

    def summary(self) -> str:
        """单行摘要 (调试用)"""
        from vision.tiles import tiles_to_str
        hand_s = tiles_to_str(self.hand_tiles)
        dora_s = tiles_to_str(self.dora_indicators)
        btns = ",".join(self.visible_buttons) if self.visible_buttons else "-"
        return (
            f"[Frame] hand({self.hand_count}): {hand_s} | "
            f"dora: {dora_s} | buttons: {btns} | "
            f"conf: {self.hand_confidence_avg:.2f}"
        )


# ═══════════════════════════════════════════════════════════════
#  VisionPipeline
# ═══════════════════════════════════════════════════════════════

class VisionPipeline:
    """
    视觉管线编排器。

    负责: 采集 → ROI 切分 → 识别 → 组装 VisionFrame。

    用法:
        pipeline = VisionPipeline(capture, regions, button_detector, tile_recognizer)
        pipeline.start()
        frame = pipeline.process_frame()
    """

    def __init__(self, capture, regions,
                 tile_recognizer=None,
                 button_detector=None):
        """
        Args:
            capture: 采集后端 (DXCAMCapture / PILCapture / ADBCapture)
            regions: ROI 布局定义 (ROIDefinition)
            tile_recognizer: TileRecognizer 实例 (None=自动创建)
            button_detector: ButtonDetector 实例 (None=自动创建)
        """
        self._capture = capture
        self._regions = regions

        # 延迟导入避免循环依赖
        if tile_recognizer is None:
            from vision.tiles import TileRecognizer
            self._tiles = TileRecognizer()
        else:
            self._tiles = tile_recognizer

        if button_detector is None:
            from vision.buttons import ButtonDetector
            self._buttons = ButtonDetector()
        else:
            self._buttons = button_detector

        # 上一帧缓存
        self._last_frame: Optional[VisionFrame] = None

        # 统计
        self._frame_count = 0
        self._total_process_time = 0.0
        self._running = False

        # 窗口矩形缓存 (通过窗口查找获取)
        self._cached_window_rect: Tuple[int, int, int, int] = (0, 0, 1920, 1080)

    # ── 生命周期 ──

    def start(self):
        """启动采集"""
        self._capture.start()
        self._running = True

    def stop(self):
        """停止采集"""
        self._running = False
        self._capture.stop()

    @property
    def running(self) -> bool:
        return self._running

    # ── 帧处理 ──

    def process_frame(self) -> Optional[VisionFrame]:
        """
        采集并处理一帧, 返回 VisionFrame。

        整个流程 (~15ms @ 1080p DXcam):
          1. 采集 (~3ms)
          2. ROI 提取 + 识别 (~10ms)
          3. 组装 (~2ms)
        """
        t0 = time.perf_counter()

        # 1. 采集
        raw = self._capture.capture()
        if raw is None:
            return self._last_frame

        h, w = raw.shape[:2]

        # 使用缓存的窗口矩形 (含多显示器偏移), 或默认全屏尺寸
        wx, wy, ww, wh = self._cached_window_rect
        if ww <= 0 or wh <= 0:
            wx, wy, ww, wh = 0, 0, w, h
        win_rect = (wx, wy, ww, wh)

        # 全屏模式: ROI 坐标是屏幕百分比
        # 窗口模式: 裁剪到窗口区域后使用窗口内百分比 ROI
        if wx != 0 or wy != 0 or ww != w or wh != h:
            # 裁剪到窗口区域
            x1, y1 = max(0, wx), max(0, wy)
            x2, y2 = min(w, wx + ww), min(h, wy + wh)
            if x2 > x1 and y2 > y1:
                raw = raw[y1:y2, x1:x2]
                w, h = x2 - x1, y2 - y1

        # 2. 识别各区域
        frame = VisionFrame(
            timestamp=time.time(),
            window_rect=win_rect,
        )

        # 手牌
        if self._tiles.is_ready:
            hand_roi = self._regions.hand.crop(raw, w, h)
            hand_results = self._tiles.recognize_hand(hand_roi, n_expected=None)
            frame.hand_tiles = [tid for tid, _ in hand_results]
            frame.hand_confidences = [cf for _, cf in hand_results]
            if frame.hand_confidences:
                frame.hand_confidence_avg = sum(frame.hand_confidences) / len(frame.hand_confidences)

            # 摸牌区
            draw_roi = self._regions.draw_tile.crop(raw, w, h)
            draw_gray = draw_roi
            if len(draw_roi.shape) == 3:
                import cv2
                draw_gray = cv2.cvtColor(draw_roi, cv2.COLOR_BGR2GRAY)
            if draw_gray.std() > 20:  # 有内容
                tile_id, _ = self._tiles.recognize_single(draw_roi)
                if tile_id >= 0:
                    frame.draw_tile = tile_id

            # 牌河 (4 家)
            for seat in range(4):
                river_roi = self._regions.get_discard_rect(seat).crop(raw, w, h)
                river_result = self._tiles.recognize_river(river_roi)
                frame.discards[seat] = [t for row in river_result for t in row]

            # 宝牌
            dora_roi = self._regions.dora.crop(raw, w, h)
            frame.dora_indicators = self._tiles.recognize_dora(dora_roi)

        # 按钮 (不依赖 tile 模板)
        btn_roi = self._regions.buttons.crop(raw, w, h)
        frame.visible_buttons = self._buttons.detect_buttons(btn_roi)

        # 3. 统计
        self._frame_count += 1
        elapsed = time.perf_counter() - t0
        self._total_process_time += elapsed

        # 缓存
        self._last_frame = frame
        return frame

    # ── 窗口管理 ──

    # 已知的雀魂窗口标题关键词 (多语言)
    _WINDOW_KEYWORDS = [
        "雀魂", "MahjongSoul", "Mahjong Soul",
        "Majsoul", "maj-soul", "JanKenPon",
    ]

    # Chrome/Edge 标签页也可能包含标题关键词
    _BROWSER_KEYWORDS = ["Chrome", "Edge", "Chromium", "Firefox"]

    def find_game_window(self) -> Optional[Tuple[int, int, int, int]]:
        """
        自动查找雀魂游戏窗口。

        搜索策略:
          1. 精确匹配窗口标题含"雀魂"或"MahjongSoul"
          2. 模糊匹配 — 排除浏览器窗口后找含关键词的窗口
          3. 如果都不行, 返回主显示器全屏尺寸

        Returns:
            (x, y, width, height) 窗口矩形, 或 None
        """
        try:
            import pygetwindow as gw
        except ImportError:
            Logger.debug("[Pipeline] pygetwindow not available")
            return None

        candidates = []
        all_windows = gw.getAllWindows()

        for win in all_windows:
            title = win.title or ""
            if not title.strip():
                continue

            # 跳过过小窗口
            if win.width < 400 or win.height < 300:
                continue

            # 跳过不可见窗口
            if not win.visible:
                continue

            matched = False
            for kw in self._WINDOW_KEYWORDS:
                if kw.lower() in title.lower():
                    matched = True
                    break

            if matched:
                # 浏览器窗口: 标题通常以 " - Google Chrome" 等结尾
                # 雀魂窗口: 标题中雀魂关键词在前
                is_browser = False
                for bkw in self._BROWSER_KEYWORDS:
                    if bkw.lower() in title.lower():
                        is_browser = True
                        break

                # 优先非浏览器窗口 (Steam/独立客户端)
                weight = 0 if not is_browser else 1
                candidates.append((weight, win.left, win.top, win.width, win.height))

        if candidates:
            # 按权重排序, 取最佳匹配
            candidates.sort(key=lambda x: x[0])
            _, x, y, w, h = candidates[0]
            Logger.info(f"[Pipeline] Found game window: '{title}' at ({x},{y}) {w}x{h}")
            return (x, y, w, h)

        return None

    def get_fullscreen_window(self) -> Tuple[int, int, int, int]:
        """
        获取当前游戏窗口的屏幕矩形。
        如果找不到窗口, 回退到主显示器 2560x1600。
        """
        rect = self.find_game_window()
        if rect is not None:
            return rect

        # 回退: 使用主显示器尺寸
        try:
            import pyautogui
            w, h = pyautogui.size()
            return (0, 0, w, h)
        except Exception:
            return (0, 0, 2560, 1600)

    def set_window_rect(self, x: int, y: int, w: int, h: int):
        """手动设置窗口矩形 (从外部窗口查找)"""
        self._cached_window_rect = (x, y, w, h)

    def update_window_rect(self):
        """
        自动查找游戏窗口并更新矩形。
        同时检测显示器变化 (多显示器/窗口拖动)。
        """
        rect = self.find_game_window()
        if rect is not None:
            self._cached_window_rect = rect

            # 更新 ROI 布局 (窗口大小可能改变了)
            self._update_regions_for_window(rect[2], rect[3])

            # 更新采集区域 (如果窗口不在主显示器)
            try:
                from vision.capture import DXCAMCapture
                outputs = DXCAMCapture.enumerate_outputs()
                if len(outputs) > 1 and hasattr(self._capture, '_config'):
                    # 检测窗口在哪个显示器上
                    wx, wy = rect[0], rect[1]
                    for o in outputs:
                        left = o.get("left", 0)
                        top = o.get("top", 0)
                        rw, rh = o.get("resolution", (1920, 1080))
                        if left <= wx < left + rw and top <= wy < top + rh:
                            self._capture._config.monitor_index = o["index"]
                            break
            except Exception:
                pass

    def _update_regions_for_window(self, win_w: int, win_h: int):
        """
        根据窗口实际尺寸更新 ROI 定义。
        从 RegionConfig 获取适配该窗口大小的布局。
        """
        try:
            from vision.regions import RegionConfig
            self._regions = RegionConfig.get_for_window(win_w, win_h)
        except Exception:
            pass  # 保留当前 ROI

    # ── 属性 ──

    @property
    def last_frame(self) -> Optional[VisionFrame]:
        return self._last_frame

    @property
    def fps(self) -> float:
        if self._frame_count == 0:
            return 0.0
        return self._frame_count / max(0.001, self._total_process_time)

    @property
    def avg_process_ms(self) -> float:
        if self._frame_count == 0:
            return 0.0
        return (self._total_process_time / self._frame_count) * 1000
