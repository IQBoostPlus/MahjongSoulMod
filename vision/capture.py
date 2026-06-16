"""
帧采集后端

支持三种采集方式，按优先级自动降级:
  1. DXCAMCapture — DXGI 显存直读, ~3ms/帧 (Windows only)
  2. PILCapture    — pyautogui.screenshot() 兼容回退, ~50ms
  3. ADBCapture    — ADB screencap, 移动端专用, ~200ms

使用:
    config = CaptureConfig(backend=CaptureBackend.DXCAM)
    capture = CaptureFactory.create(config)
    frame = capture.capture()  # np.ndarray (H, W, 3) BGR
"""

import time
import os
import sys
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from utils.log import Logger


class CaptureBackend(Enum):
    """采集后端枚举"""
    DXCAM = "dxcam"
    PIL = "pil"
    ADB = "adb"
    AUTO = "auto"  # 自动选择最佳可用后端


@dataclass
class CaptureConfig:
    """采集配置"""
    backend: CaptureBackend = CaptureBackend.AUTO
    target_fps: int = 10                    # 目标帧率
    region: Optional[Tuple[int, int, int, int]] = None  # (left, top, right, bottom) 采集区域
    mobile_device_id: Optional[str] = None  # ADB 设备 ID
    output_color: str = "BGR"               # "BGR" | "RGB" | "GRAY"
    monitor_index: int = 0                  # 显示器索引 (0=主显示器, 多显示器时指定)
    device_idx: int = 0                     # DXGI 适配器索引 (0=默认GPU)


# ═══════════════════════════════════════════════════════════════
#  DXcam 采集 (Windows DXGI)
# ═══════════════════════════════════════════════════════════════

class DXCAMCapture:
    """
    Windows DXGI 屏幕采集, ~3ms/帧。

    走 DirectX Graphics Infrastructure, 直接从显存拿帧,
    比 pyautogui (GDI) 快 15 倍以上且不干扰光标操作。
    """

    def __init__(self, config: CaptureConfig):
        self._config = config
        self._camera = None
        self._dxcam = None
        self._last_frame: Optional[np.ndarray] = None
        self._last_capture_time = 0.0
        self._frame_count = 0
        self._start_time = 0.0

    def start(self) -> bool:
        """初始化 DXcam 相机"""
        try:
            import dxcam
            self._dxcam = dxcam

            region = self._config.region

            # 枚举可用输出 (显示器)
            outputs = DXCAMCapture.enumerate_outputs()
            output_idx = self._config.monitor_index if self._config.monitor_index < len(outputs) else 0
            if self._config.monitor_index > 0 and output_idx == 0:
                Logger.warning(f"[DXcam] Monitor {self._config.monitor_index} not found, using primary")

            self._camera = dxcam.create(
                device_idx=self._config.device_idx,
                output_idx=output_idx,
                region=region,
                output_color=self._config.output_color,
            )

            if self._camera is None:
                Logger.warning("[DXcam] No output device found, falling back to PIL")
                return False

            # 预热 — 触发 D3D11 设备创建
            _ = self._camera.grab()
            self._start_time = time.time()
            Logger.info(f"[DXcam] Started on output {output_idx} (target: {self._config.target_fps} FPS)")
            return True
        except ImportError:
            Logger.warning("[DXcam] dxcam not installed — falling back to PIL")
            return False
        except Exception as e:
            Logger.warning(f"[DXcam] Init failed: {e} — falling back to PIL")
            return False

    def capture(self) -> Optional[np.ndarray]:
        """截取一帧, 返回 numpy array (H, W, 3) BGR 或 None"""
        if self._camera is None:
            return None

        try:
            # DXcam 内部有帧率控制, grab() 自带节流
            frame = self._camera.grab()
            if frame is None:
                return self._last_frame  # 返回上一帧

            # DXcam 返回 BGRA (H, W, 4), 去掉 alpha 通道
            if frame.shape[-1] == 4:
                frame = frame[:, :, :3]

            color = self._config.output_color
            if color == "RGB":
                frame = frame[:, :, ::-1]  # BGR → RGB
            elif color == "GRAY":
                import cv2
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            self._last_frame = frame
            self._last_capture_time = time.time()
            self._frame_count += 1
            return frame
        except Exception as e:
            Logger.debug(f"[DXcam] Capture error: {e}")
            return self._last_frame

    def stop(self):
        """释放相机资源"""
        if self._camera is not None:
            try:
                del self._camera
            except Exception:
                pass
            self._camera = None
        Logger.debug("[DXcam] Stopped")

    @staticmethod
    def enumerate_outputs() -> List[dict]:
        """
        枚举所有可用显示器输出。

        Returns:
            [{"index": 0, "name": "\\\\.\\DISPLAY1", "resolution": (1920, 1080), "primary": True}, ...]
        """
        outputs = []
        try:
            import dxcam
            # DXcam 通过 DXGI 枚举输出
            camera = dxcam.create()
            if camera is not None:
                # 尝试获取输出信息
                try:
                    info = camera.info
                    if info:
                        outputs.append({
                            "index": 0,
                            "name": info.get("output_name", "DISPLAY1"),
                            "resolution": (
                                info.get("width", 1920),
                                info.get("height", 1080),
                            ),
                            "primary": True,
                        })
                except Exception:
                    pass
                camera.release()
        except ImportError:
            pass

        # 回退: 使用 Windows API 枚举 (更可靠)
        if not outputs and sys.platform == "win32":
            try:
                import ctypes
                from ctypes import wintypes

                user32 = ctypes.windll.user32

                monitors = []
                def _monitor_enum_proc(hMonitor, hdcMonitor, lprcMonitor, dwData):
                    rect = lprcMonitor.contents
                    monitors.append({
                        "index": len(monitors),
                        "name": f"DISPLAY{len(monitors) + 1}",
                        "resolution": (
                            rect.right - rect.left,
                            rect.bottom - rect.top,
                        ),
                        "left": rect.left,
                        "top": rect.top,
                        "primary": len(monitors) == 0,
                    })
                    return True

                MonitorEnumProc = ctypes.WINFUNCTYPE(
                    wintypes.BOOL,
                    wintypes.HMONITOR,
                    wintypes.HDC,
                    ctypes.POINTER(wintypes.RECT),
                    wintypes.LPARAM,
                )

                class RECT(ctypes.Structure):
                    _fields_ = [
                        ("left", wintypes.LONG),
                        ("top", wintypes.LONG),
                        ("right", wintypes.LONG),
                        ("bottom", wintypes.LONG),
                    ]

                user32.EnumDisplayMonitors(None, None, MonitorEnumProc(_monitor_enum_proc), 0)
                outputs.extend(monitors)
            except Exception:
                pass

        # 最终回退
        if not outputs:
            outputs.append({
                "index": 0, "name": "DISPLAY1",
                "resolution": (1920, 1080), "primary": True,
            })

        return outputs

    @property
    def fps(self) -> float:
        """实际帧率"""
        if self._start_time == 0 or self._frame_count == 0:
            return 0.0
        elapsed = time.time() - self._start_time
        return self._frame_count / elapsed if elapsed > 0 else 0.0


# ═══════════════════════════════════════════════════════════════
#  PIL/pyautogui 采集 (GDI 兼容回退)
# ═══════════════════════════════════════════════════════════════

class PILCapture:
    """
    pyautogui 截图回退, 走 Windows GDI, ~50ms/帧。

    所有平台通用, 始终可用, 作为最后的安全网。
    """

    def __init__(self, config: CaptureConfig):
        self._config = config
        self._last_frame: Optional[np.ndarray] = None
        self._last_capture_time = 0.0
        self._frame_count = 0
        self._start_time = 0.0
        self._pyautogui = None

    def start(self) -> bool:
        """初始化 pyautogui"""
        try:
            import pyautogui
            self._pyautogui = pyautogui

            # 获取目标显示器偏移量 (多显示器)
            self._monitor_offset = (0, 0)
            if self._config.monitor_index > 0:
                outputs = DXCAMCapture.enumerate_outputs()
                for o in outputs:
                    if o.get("index") == self._config.monitor_index:
                        self._monitor_offset = (o.get("left", 0), o.get("top", 0))
                        break
                if self._monitor_offset != (0, 0):
                    Logger.info(f"[PIL] Monitor offset: {self._monitor_offset}")

            self._start_time = time.time()
            Logger.info("[PIL] Started (pyautogui GDI fallback)")
            return True
        except ImportError:
            Logger.error("[PIL] pyautogui not installed")
            return False
        except Exception as e:
            Logger.error(f"[PIL] Init failed: {e}")
            return False

    def capture(self) -> Optional[np.ndarray]:
        """截取一帧"""
        if self._pyautogui is None:
            return None

        try:
            import cv2

            region = self._config.region
            if region is not None:
                # 应用显示器偏移
                ox, oy = getattr(self, '_monitor_offset', (0, 0))
                if ox != 0 or oy != 0:
                    region = (
                        region[0] + ox, region[1] + oy,
                        region[2] + ox, region[3] + oy,
                    )
                img = self._pyautogui.screenshot(region=region)
            else:
                img = self._pyautogui.screenshot()

            frame = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

            color = self._config.output_color
            if color == "RGB":
                frame = frame[:, :, ::-1]
            elif color == "GRAY":
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            self._last_frame = frame
            self._last_capture_time = time.time()
            self._frame_count += 1
            return frame
        except Exception as e:
            Logger.debug(f"[PIL] Capture error: {e}")
            return self._last_frame

    def stop(self):
        self._pyautogui = None
        Logger.debug("[PIL] Stopped")

    @property
    def fps(self) -> float:
        if self._start_time == 0 or self._frame_count == 0:
            return 0.0
        elapsed = time.time() - self._start_time
        return self._frame_count / elapsed if elapsed > 0 else 0.0


# ═══════════════════════════════════════════════════════════════
#  ADB 采集 (移动端)
# ═══════════════════════════════════════════════════════════════

class ADBCapture:
    """
    移动端 ADB screencap 采集, ~200ms/帧。

    适用于 Android 手机/平板运行雀魂的场景。
    """

    def __init__(self, config: CaptureConfig):
        self._config = config
        self._device_id = config.mobile_device_id
        self._last_frame: Optional[np.ndarray] = None
        self._last_capture_time = 0.0
        self._frame_count = 0
        self._start_time = 0.0
        self._adapter = None  # MobileActionExecutor adapter

    def start(self) -> bool:
        """初始化 ADB 连接"""
        try:
            from action.mobile_executor import ADB as _ADB
            self._adapter = _ADB

            # 自动检测设备
            if not self._device_id:
                devices = _ADB.devices()
                if devices:
                    self._device_id = devices[0]
                    Logger.info(f"[ADB] Auto-detected device: {self._device_id}")
                else:
                    Logger.warning("[ADB] No devices found via adb")
                    return False

            # 验证连接
            size = _ADB.get_screen_size(self._device_id)
            if size:
                Logger.info(f"[ADB] Device {self._device_id}: {size[0]}x{size[1]}")
                self._start_time = time.time()
                return True
            return False
        except ImportError:
            Logger.warning("[ADB] action.mobile_executor not available")
            return False
        except Exception as e:
            Logger.warning(f"[ADB] Init failed: {e}")
            return False

    def capture(self) -> Optional[np.ndarray]:
        """ADB 截图"""
        if self._adapter is None or self._device_id is None:
            return None

        try:
            import cv2
            import tempfile
            import os

            # screencap → pull → read
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                tmp_path = f.name

            ok = self._adapter.screenshot(self._device_id, tmp_path)
            if not ok or not os.path.isfile(tmp_path):
                return self._last_frame

            frame = cv2.imread(tmp_path, cv2.IMREAD_COLOR)
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

            if frame is None:
                return self._last_frame

            color = self._config.output_color
            if color == "RGB":
                frame = frame[:, :, ::-1]
            elif color == "GRAY":
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            self._last_frame = frame
            self._last_capture_time = time.time()
            self._frame_count += 1
            return frame
        except Exception as e:
            Logger.debug(f"[ADB] Capture error: {e}")
            return self._last_frame

    def stop(self):
        self._adapter = None
        Logger.debug("[ADB] Stopped")

    @property
    def fps(self) -> float:
        if self._start_time == 0 or self._frame_count == 0:
            return 0.0
        elapsed = time.time() - self._start_time
        return self._frame_count / elapsed if elapsed > 0 else 0.0


# ═══════════════════════════════════════════════════════════════
#  CaptureFactory
# ═══════════════════════════════════════════════════════════════

class CaptureFactory:
    """
    采集后端工厂。

    用法:
        config = CaptureConfig(backend=CaptureBackend.AUTO)
        capture = CaptureFactory.create(config)
        capture.start()
        frame = capture.capture()
    """

    @staticmethod
    def create(config: CaptureConfig):
        """
        根据配置创建采集后端。

        AUTO 模式优先级: DXcam → PIL
        移动端: ADB
        """
        backend = config.backend

        if backend == CaptureBackend.ADB:
            return ADBCapture(config)

        if backend == CaptureBackend.DXCAM:
            cap = DXCAMCapture(config)
            if cap.start():
                return cap
            Logger.warning("[Capture] DXcam failed, falling back to PIL")
            return CaptureFactory._create_pil(config)

        if backend == CaptureBackend.PIL:
            return CaptureFactory._create_pil(config)

        # AUTO: 尝试 DXcam, 回退 PIL
        if backend == CaptureBackend.AUTO:
            cap = DXCAMCapture(config)
            if cap.start():
                return cap
            Logger.info("[Capture] DXcam unavailable, using PIL fallback")
            return CaptureFactory._create_pil(config)

        # 兜底
        return CaptureFactory._create_pil(config)

    @staticmethod
    def _create_pil(config: CaptureConfig) -> PILCapture:
        cap = PILCapture(config)
        cap.start()
        return cap
