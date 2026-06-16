"""
Score OCR — 使用 PaddleOCR 从游戏屏幕读取分数和局况信息

PaddleOCR 已内置中文/日文识别, 可直接读取雀魂界面上的:
  - 各家分数 (4 家点数)
  - 场风/局数 (東1局, 南2局 等)
  - 本场数 (供托/立直棒)
  - 剩余牌数

用法:
    ocr = ScoreOCR()
    ocr.initialize()  # 首次加载模型 (~2-5 秒)
    scores = ocr.read_scores(info_crop, score_crops)
    # scores: {"self": 25000, "shimo": 25000, "toimen": 25000, "kamicha": 25000}

设计原则:
  - 延迟加载: PaddleOCR 模型 (数百MB) 仅在首次使用时加载
  - 缓存复用: 连续帧的 OCR 结果用多数投票平滑
  - 回退安全: OCR 失败返回 None, 不阻塞主循环
"""

import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

import numpy as np

from utils.log import Logger


@dataclass
class ScoreInfo:
    """一帧的分数字识别结果"""
    scores: List[int] = field(default_factory=lambda: [25000, 25000, 25000, 25000])
    # seat order: 0=自家, 1=下家, 2=对家, 3=上家
    round_wind: int = 0       # 0=东, 1=南, 2=西, 3=北
    round_number: int = 0     # 0-3
    honba: int = 0            # 本场数
    deposits: int = 0         # 供托 (立直棒)
    tiles_left: int = 70      # 剩余牌数
    confidence: float = 0.0   # 整体识别置信度

    @property
    def scores_valid(self) -> bool:
        """所有分数都在合法范围"""
        return all(0 <= s <= 200000 for s in self.scores)


class ScoreOCR:
    """
    PaddleOCR 包装器, 专用于雀魂界面文字识别。

    特性:
      - 延迟初始化 (首次调用时加载模型)
      - 文本后处理 (正则提取数字/场风)
      - 连续帧多数投票去噪
    """

    # 场风关键词
    WIND_MAP = {"東": 0, "东": 0, "南": 1, "西": 2, "北": 3}

    # 局数关键词 (支持中日文)
    ROUND_MAP = {
        "1局": 0, "2局": 1, "3局": 2, "4局": 3,
        "１局": 0, "２局": 1, "３局": 2, "４局": 3,
    }

    def __init__(self, lang: str = "ch", use_gpu: bool = True):
        """
        Args:
            lang: OCR 语言 ("ch" = 中文+英文, "japan" = 日文)
            use_gpu: 是否使用 GPU 推理 (推荐, 速度快 5-10x)
        """
        self._lang = lang
        self._use_gpu = use_gpu
        self._ocr = None
        self._initialized = False
        self._init_attempted = False

        # 连续帧缓存 (多数投票用)
        self._score_history: List[List[int]] = []
        self._round_history: List[Tuple[int, int]] = []
        self._max_history = 5

    # ── 初始化 ──

    def initialize(self) -> bool:
        """
        初始化 PaddleOCR 引擎。
        首次调用耗时 ~2-5 秒 (加载模型文件)。
        后续调用是空操作。
        """
        if self._initialized:
            return True
        if self._init_attempted:
            return False

        self._init_attempted = True
        try:
            from paddleocr import PaddleOCR
            self._ocr = PaddleOCR(
                lang=self._lang,
                use_angle_cls=True,   # 文字方向分类 (提高精度)
                use_gpu=self._use_gpu,
                show_log=False,
            )
            self._initialized = True
            Logger.info(f"[OCR] PaddleOCR initialized (lang={self._lang}, gpu={self._use_gpu})")
            return True
        except ImportError:
            Logger.warning("[OCR] PaddleOCR not installed — score reading disabled")
            Logger.warning("[OCR] Install: pip install paddleocr paddlepaddle")
            return False
        except Exception as e:
            Logger.warning(f"[OCR] PaddleOCR init failed: {e}")
            return False

    @property
    def is_ready(self) -> bool:
        return self._initialized

    # ── 公开 API ──

    def read_all(self, info_crop: np.ndarray,
                 score_crops: List[np.ndarray]) -> Optional[ScoreInfo]:
        """
        从信息栏和分数区域读取完整局况。

        Args:
            info_crop: 信息栏区域截图 (BGR)
            score_crops: 4 家分数区域截图列表 [自家, 下家, 对家, 上家]

        Returns:
            ScoreInfo 或 None (识别失败时)
        """
        if not self.initialize():
            return None

        scores = [25000, 25000, 25000, 25000]
        for i, crop in enumerate(score_crops):
            val = self._read_number(crop)
            if val is not None and 0 <= val <= 200000:
                scores[i] = val

        # 读取信息栏
        round_wind, round_number, honba, deposits = self._read_round_info(info_crop)

        # 平滑: 多数投票
        scores = self._smooth_scores(scores)
        rw, rn = self._smooth_round(round_wind, round_number)

        confidence = 0.0
        # 简单置信度: 分数非默认的比例
        non_default = sum(1 for s in scores if s != 25000)
        confidence = non_default / 4.0

        return ScoreInfo(
            scores=scores,
            round_wind=rw,
            round_number=rn,
            honba=honba,
            deposits=deposits,
            confidence=confidence,
        )

    def read_scores(self, info_crop: np.ndarray,
                    score_crops: List[np.ndarray]) -> Optional[List[int]]:
        """仅读取 4 家分数, 返回 [自家, 下家, 对家, 上家] 或 None"""
        result = self.read_all(info_crop, score_crops)
        return result.scores if result else None

    def read_game_info(self, info_crop: np.ndarray) -> Dict:
        """
        从信息栏读取局况 (不读分数)。

        Returns:
            {"round_wind": 0, "round_number": 0, "honba": 0, "deposits": 0}
        """
        if not self.initialize():
            return {}
        rw, rn, honba, dep = self._read_round_info(info_crop)
        return {
            "round_wind": rw,
            "round_number": rn,
            "honba": honba,
            "deposits": dep,
        }

    def read_text(self, image: np.ndarray) -> List[Tuple[str, float]]:
        """
        通用文字识别。返回 [(文字, 置信度), ...]

        用于调试或识别任意游戏文字。
        """
        if not self.initialize():
            return []
        results = self._ocr.ocr(image)
        if not results or not results[0]:
            return []

        texts = []
        for line in results[0]:
            if line is None:
                continue
            bbox, (text, confidence) = line
            texts.append((text, confidence))
        return texts

    # ── 内部识别 ──

    def _read_number(self, image: np.ndarray) -> Optional[int]:
        """
        从分数区域图片中读取数字。

        雀魂的分数显示为白色数字 (如 "25000")。
        PaddleOCR 对数字识别准确率高。
        """
        if image is None or image.size == 0:
            return None

        results = self._ocr.ocr(image)
        if not results or not results[0]:
            return None

        # 收集所有识别出的数字
        for line in results[0]:
            if line is None:
                continue
            bbox, (text, conf) = line
            # 提取数字
            num_str = re.sub(r'[^\d]', '', text)
            if num_str and len(num_str) >= 3:
                try:
                    return int(num_str)
                except ValueError:
                    continue

        return None

    def _read_round_info(self, info_crop: np.ndarray) -> Tuple[int, int, int, int]:
        """
        从信息栏区域读取局况信息。

        识别模式: "東1局" → round_wind=0, round_number=0
                  "南2局 本場1" → round_wind=1, round_number=1, honba=1
                  "供託2" → deposits=2
        """
        if info_crop is None or info_crop.size == 0:
            return 0, 0, 0, 0

        results = self._ocr.ocr(info_crop)
        if not results or not results[0]:
            return 0, 0, 0, 0

        all_text = ""
        for line in results[0]:
            if line is None:
                continue
            bbox, (text, conf) = line
            all_text += text

        return self._parse_round_text(all_text)

    @classmethod
    def _parse_round_text(cls, text: str) -> Tuple[int, int, int, int]:
        """从 OCR 文本解析局况信息"""
        round_wind = 0
        round_number = 0
        honba = 0
        deposits = 0

        # 检测场风
        for wind_char, wind_id in cls.WIND_MAP.items():
            if wind_char in text:
                round_wind = wind_id
                break

        # 检测局数
        for round_str, round_id in cls.ROUND_MAP.items():
            if round_str in text:
                round_number = round_id
                break

        # 检测本场
        honba_match = re.search(r'本場\s*(\d+)', text)
        if not honba_match:
            honba_match = re.search(r'本场\s*(\d+)', text)
        if not honba_match:
            honba_match = re.search(r'(\d+)\s*本場', text)
        if honba_match:
            try:
                honba = int(honba_match.group(1))
            except ValueError:
                pass

        # 检测供托
        dep_match = re.search(r'供託\s*(\d+)', text)
        if not dep_match:
            dep_match = re.search(r'供托\s*(\d+)', text)
        if dep_match:
            try:
                deposits = int(dep_match.group(1))
            except ValueError:
                pass

        return round_wind, round_number, honba, deposits

    # ── 连续帧平滑 ──

    def _smooth_scores(self, new_scores: List[int]) -> List[int]:
        """多数投票平滑分数"""
        self._score_history.append(new_scores)
        if len(self._score_history) > self._max_history:
            self._score_history.pop(0)

        if len(self._score_history) < 3:
            return new_scores

        # 对每个座位, 取最近帧的众数
        smoothed = []
        for seat in range(4):
            vals = [h[seat] for h in self._score_history]
            # 取最频繁的值, 平局时取最新
            from collections import Counter
            counter = Counter(vals)
            most_common = counter.most_common(1)[0][0]
            smoothed.append(most_common)

        return smoothed

    def _smooth_round(self, wind: int, num: int) -> Tuple[int, int]:
        """多数投票平滑局况"""
        self._round_history.append((wind, num))
        if len(self._round_history) > self._max_history:
            self._round_history.pop(0)

        if len(self._round_history) < 3:
            return wind, num

        winds = [h[0] for h in self._round_history]
        nums = [h[1] for h in self._round_history]

        from collections import Counter
        w = Counter(winds).most_common(1)[0][0]
        n = Counter(nums).most_common(1)[0][0]
        return w, n

    # ── 属性 ──

    @property
    def lang(self) -> str:
        return self._lang

    @property
    def use_gpu(self) -> bool:
        return self._use_gpu
