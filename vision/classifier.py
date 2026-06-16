"""
神经网络牌分类器 — ONNX MobileNetV3 / ViT 推理

当 ONNX 模型文件存在时启用, 否则自动禁用。
用于模板匹配低置信度时的降级方案。

模型文件:
  vision/models/tile_classifier.onnx  — MobileNetV3 (轻量, CPU ~5ms)
  vision/models/tile_vit.onnx         — ViT-B/16 (高精度 99.67%, CPU ~50ms)

优先级: 模板匹配 (快速) → ONNX (精确) → 坐标估算 (兜底)

用法:
    from vision.classifier import NeuralTileClassifier
    nn = NeuralTileClassifier()
    if nn.available:
        tile_id, conf = nn.classify(tile_roi)
"""

import os
from typing import Dict, List, Optional, Tuple

import numpy as np

from utils.log import Logger


class NeuralTileClassifier:
    """
    ONNX 神经网络牌分类器。

    支持:
      - MobileNetV3-Small: 输入 64×64, 37 类输出, ~5ms CPU
      - ViT-B/16: 输入 224×224, 37 类输出, ~50ms CPU, 99.67% 准确率

    自举训练: 用模板匹配高置信度 (>0.95) 的结果自动标注,
              积累足够样本后微调模型。
    """

    MODEL_DIR = os.path.join(os.path.dirname(__file__), "models")

    # 模型配置文件
    MODEL_CONFIGS = {
        "tile_classifier.onnx": {
            "input_size": (64, 64),
            "input_name": "input",
            "output_name": "output",
            "num_classes": 37,
            "description": "MobileNetV3-Small (fast)",
        },
        "tile_vit.onnx": {
            "input_size": (224, 224),
            "input_name": "pixel_values",
            "output_name": "logits",
            "num_classes": 37,
            "description": "ViT-B/16 (accurate, 99.67%)",
        },
    }

    def __init__(self, model_name: str = None):
        """
        Args:
            model_name: 模型文件名 (None=自动选择第一个可用的)
        """
        self._session = None
        self._model_name = None
        self._config = None

        # 尝试加载 ONNX Runtime
        try:
            import onnxruntime as ort
            self._ort = ort
        except ImportError:
            Logger.debug("[NN] onnxruntime not installed — neural classifier disabled")
            self._ort = None
            return

        # 加载模型
        if model_name:
            self._load_model(model_name)
        else:
            self._auto_load()

    # ── 模型加载 ──

    def _auto_load(self):
        """自动选择第一个可用的模型"""
        for model_name in self.MODEL_CONFIGS:
            if self._load_model(model_name):
                return

    def _load_model(self, model_name: str) -> bool:
        """加载指定 ONNX 模型"""
        if self._ort is None:
            return False

        model_path = os.path.join(self.MODEL_DIR, model_name)
        if not os.path.isfile(model_path):
            Logger.debug(f"[NN] Model not found: {model_path}")
            return False

        config = self.MODEL_CONFIGS.get(model_name, {})
        if not config:
            Logger.warning(f"[NN] Unknown model: {model_name}")
            return False

        try:
            self._session = self._ort.InferenceSession(
                model_path,
                providers=['CPUExecutionProvider']
            )
            self._model_name = model_name
            self._config = config
            Logger.info(f"[NN] Loaded {config['description']}: {model_path}")
            return True
        except Exception as e:
            Logger.warning(f"[NN] Failed to load {model_name}: {e}")
            return False

    @property
    def available(self) -> bool:
        return self._session is not None

    @property
    def model_name(self) -> str:
        return self._model_name or "none"

    # ── 推理 ──

    def classify(self, tile_roi: np.ndarray) -> Tuple[int, float]:
        """
        分类单张牌。

        Args:
            tile_roi: 裁剪后的牌面图像 (BGR 或灰度, 任意尺寸)

        Returns:
            (tile_id: 0-36, confidence: 0.0-1.0)
            模型不可用时返回 (-1, 0.0)
        """
        if not self.available:
            return (-1, 0.0)

        try:
            import cv2

            # 预处理: 转 RGB → resize → normalize
            if len(tile_roi.shape) == 2:
                img = cv2.cvtColor(tile_roi, cv2.COLOR_GRAY2RGB)
            else:
                img = cv2.cvtColor(tile_roi, cv2.COLOR_BGR2RGB)

            target_size = self._config["input_size"]
            img = cv2.resize(img, target_size)

            # 归一化到 [0, 1]
            img = img.astype(np.float32) / 255.0

            # 标准 ImageNet 归一化
            mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
            std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
            img = (img - mean) / std

            # NCHW: (H, W, C) → (1, C, H, W)
            img = np.transpose(img, (2, 0, 1))
            img = np.expand_dims(img, axis=0)

            # 推理
            input_name = self._config.get("input_name", "input")
            output_name = self._config.get("output_name", "output")

            outputs = self._session.run(
                [output_name], {input_name: img}
            )
            logits = outputs[0][0]

            # Softmax
            exp_logits = np.exp(logits - np.max(logits))
            probs = exp_logits / exp_logits.sum()

            tile_id = int(np.argmax(probs))
            confidence = float(np.max(probs))

            return (tile_id, confidence)

        except Exception as e:
            Logger.debug(f"[NN] Inference failed: {e}")
            return (-1, 0.0)

    def classify_batch(self, tile_rois: List[np.ndarray]) -> List[Tuple[int, float]]:
        """批量分类 (暂用循环实现)"""
        return [self.classify(roi) for roi in tile_rois]


class BootstrapTrainer:
    """
    自举训练器 — 用模板匹配高置信度结果自动标注样本。

    流程:
      1. 模板匹配得到高置信度结果 (conf > 0.95)
      2. 保存 (tile_roi, tile_id) 到训练集
      3. 积累足够样本后, 微调 ONNX 模型
      4. 新模型替换旧模型, 提高后续准确率

    这是数据飞轮的核心 — 用越多, 越准。
    """

    TRAINING_DIR = os.path.join(
        os.path.dirname(__file__), "models", "training_data"
    )

    def __init__(self, min_confidence: float = 0.95):
        self._min_confidence = min_confidence
        self._buffer: Dict[int, List[np.ndarray]] = {}  # tile_id → [images]
        self._max_buffer = 200  # 每类最多存 200 张

    def add_sample(self, tile_roi: np.ndarray, tile_id: int, confidence: float):
        """添加一个高置信度样本"""
        if confidence < self._min_confidence:
            return
        if tile_id < 0 or tile_id > 36:
            return

        if tile_id not in self._buffer:
            self._buffer[tile_id] = []

        if len(self._buffer[tile_id]) < self._max_buffer:
            self._buffer[tile_id].append(tile_roi)

    def get_sample_counts(self) -> Dict[int, int]:
        """获取各类样本数"""
        return {k: len(v) for k, v in self._buffer.items()}

    def is_ready_to_train(self, min_per_class: int = 20) -> bool:
        """是否有足够样本用于训练"""
        counts = self.get_sample_counts()
        if len(counts) < 30:  # 至少覆盖 30 类
            return False
        return all(c >= min_per_class for c in counts.values())

    def save_dataset(self):
        """保存训练数据集到磁盘"""
        import cv2
        os.makedirs(self.TRAINING_DIR, exist_ok=True)

        total = 0
        for tile_id, images in self._buffer.items():
            class_dir = os.path.join(self.TRAINING_DIR, str(tile_id))
            os.makedirs(class_dir, exist_ok=True)

            for i, img in enumerate(images):
                path = os.path.join(class_dir, f"{i:04d}.png")
                cv2.imwrite(path, img)
                total += 1

        Logger.info(f"[Bootstrap] Saved {total} training samples to {self.TRAINING_DIR}")
        return total
