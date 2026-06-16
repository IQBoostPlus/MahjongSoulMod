"""
Vision-First Pipeline — 屏幕视觉识别引擎

通过 DXcam 高速截帧 + 多尺度模板匹配识别牌面和按钮,
替代原有的 MITM 代理 + Protobuf 协议解码方案。

模块:
  - capture.py:  帧采集后端 (DXcam / PIL / ADB)
  - regions.py:  ROI 区域定义 (归一化坐标)
  - tiles.py:    牌面识别 (模板匹配 + ONNX 降级)
  - pipeline.py: 管线编排 + VisionFrame 输出
  - differ.py:   帧差分 → 游戏事件推断
  - processor.py: 事件桥接 → GameTracker
  - buttons.py:  按钮检测 (Airtest/OpenCV)
  - verifier.py: Plan→Execute→Verify 闭环
  - executor.py: 视觉驱动动作执行器
  - ocr.py:      PaddleOCR 分数/局况识别
  - classifier.py: ONNX 神经网络分类器
"""

from .capture import (
    CaptureConfig,
    CaptureBackend,
    CaptureFactory,
    DXCAMCapture,
    PILCapture,
    ADBCapture,
)

from .regions import (
    Rect,
    ROIDefinition,
    RegionConfig,
    REGION_PRESETS,
)

from .tiles import (
    TileTemplateMatcher,
    TileRecognizer,
    TILE_NAMES,
    tile_to_name,
    tiles_to_str,
)

from .classifier import (
    NeuralTileClassifier,
    BootstrapTrainer,
)

from .pipeline import (
    VisionFrame,
    MeldInfo,
    RoundInfo,
    VisionPipeline,
)

from .differ import (
    VisionEvent,
    StateDiffer,
    StatefulDiffer,
)

from .processor import (
    VisionEventProcessor,
)

from .buttons import (
    ButtonDetector,
    NullButtonDetector,
)

from .verifier import (
    ActionVerifier,
)

from .executor import (
    VisionActionExecutor,
)

from .ocr import (
    ScoreOCR,
    ScoreInfo,
)

__all__ = [
    # Capture
    "CaptureConfig", "CaptureBackend", "CaptureFactory",
    "DXCAMCapture", "PILCapture", "ADBCapture",
    # Regions
    "Rect", "ROIDefinition", "RegionConfig", "REGION_PRESETS",
    # Tiles
    "TileTemplateMatcher", "TileRecognizer",
    "TILE_NAMES", "tile_to_name", "tiles_to_str",
    # Classifier
    "NeuralTileClassifier", "BootstrapTrainer",
    # Pipeline
    "VisionFrame", "MeldInfo", "RoundInfo", "VisionPipeline",
    # Differ
    "VisionEvent", "StateDiffer", "StatefulDiffer",
    # Processor
    "VisionEventProcessor",
    # Buttons
    "ButtonDetector", "NullButtonDetector",
    # Verifier
    "ActionVerifier",
    # Executor
    "VisionActionExecutor",
    # OCR
    "ScoreOCR", "ScoreInfo",
]
