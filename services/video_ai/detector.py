"""视频 AI 参考推理检测器（⑧ 真实推理服务部署 · 参考实现）。

本模块实现「平台 → 外部推理服务」契约的**服务端**：接收平台下发的
``{"payload": {...}}``，对帧做**真实像素级**分析后返回结构化 ``findings``。

- ``ReferenceDetector``：纯 Pillow + numpy 的启发式检测器，**真实处理图像像素**
  （HSV/RGB 色彩掩膜 + 危险区规则），不依赖任何训练模型，可直接运行，
  作为生产 YOLO 等模型的**可替换占位**（reference stand-in）。
- ``YoloDetector``：可插拔的真实模型接口（需安装 ``ultralytics`` + 权重），
  同一 ``detect(image) -> findings`` 契约，秒级切换为生产模型。

能力清单 ``CAPABILITIES`` 与平台 ``app.schema.video.VIDEO_AI_CAPABILITY_TYPES``
保持一致（单一事实来源由平台侧维护，此处做镜像以便服务自描述）。
"""

from __future__ import annotations

import base64
import io
from typing import List, Protocol, runtime_checkable

import numpy as np
from PIL import Image, ImageDraw

# 与平台 VIDEO_AI_CAPABILITIES 对齐（类型/标签镜像）
CAPABILITIES: List[dict] = [
    {"type": "intrusion", "label": "区域入侵"},
    {"type": "no_helmet", "label": "未戴安全帽"},
    {"type": "smoke_fire", "label": "烟火"},
    {"type": "other", "label": "其他"},
]
_CAPABILITY_TYPES = {c["type"] for c in CAPABILITIES}
_LABELS = {c["type"]: c["label"] for c in CAPABILITIES}


def _label_of(ftype: str) -> str:
    return _LABELS.get(ftype, ftype)


@runtime_checkable
class Detector(Protocol):
    name: str

    def detect(self, image: Image.Image) -> List[dict]:
        """返回 findings 列表；空列表表示未识别到异常。"""
        ...


def load_frame(payload: dict) -> Image.Image | None:
    """从 payload 加载待分析帧。

    支持三种来源（优先级）：``demo``（合成测试帧）、``frame_url``（远程下载）、
    ``frame_b64``（base64，支持 data URL 前缀）。无帧时返回 ``None``。
    任何加载失败都返回 ``None``，由调用方决定降级为「0 项 findings」。
    """
    if payload.get("demo"):
        return _demo_image()
    fu = payload.get("frame_url")
    if fu:
        try:
            import urllib.request

            with urllib.request.urlopen(fu, timeout=5) as resp:
                return Image.open(io.BytesIO(resp.read())).convert("RGB")
        except Exception:
            return None
    b64 = payload.get("frame_b64")
    if b64:
        try:
            if "," in b64:
                b64 = b64.split(",", 1)[1]
            return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
        except Exception:
            return None
    return None


def _demo_image() -> Image.Image:
    """合成一帧：顶部红色火点 + 底部危险区肤色人形（用于无真实帧的联调）。"""
    img = Image.new("RGB", (640, 480), (28, 30, 34))
    d = ImageDraw.Draw(img)
    d.ellipse([300, 36, 392, 128], fill=(222, 44, 30))  # 烟火
    d.ellipse([120, 360, 212, 452], fill=(205, 162, 132))  # 危险区人形/肤色
    return img


class ReferenceDetector:
    """纯像素启发式检测器（参考实现，可运行、可替换）。

    规则（参考性质，非生产精度）：
    - ``smoke_fire``：高红/高饱和火点掩膜。
    - ``intrusion``：危险区（底部 40%）内的肤色/衣物色块。
    - ``no_helmet``：危险区外的肤色色块（视为未佩戴安全帽的人形头肩）。
    置信度由掩膜面积占比映射，bbox 由掩膜像素极值计算。
    """

    name = "rail-reference-detector-v1"

    def detect(self, image: Image.Image) -> List[dict]:
        arr = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
        h, w, _ = arr.shape
        r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]

        # 肤色掩膜（简化规则）
        skin = (r > 0.5) & (g > 0.35) & (g < 0.78) & (r > g) & (g > b) & ((r - g) > 0.06)
        # 火点掩膜：高红、低蓝、高红蓝差
        fire = (r > 0.6) & (b < 0.35) & ((r - b) > 0.35)

        findings: List[dict] = []
        # 烟火：全图火点掩膜
        findings += self._from_mask(fire, (h, w), "smoke_fire", min_area=0.0015)
        # 区域入侵：危险区（底部 40%）内肤色/衣物
        dz = np.zeros_like(skin)
        dz[int(h * 0.6) :, :] = skin[int(h * 0.6) :, :]
        findings += self._from_mask(dz, (h, w), "intrusion", min_area=0.0012)
        # 未戴安全帽：危险区外肤色（视作头肩裸露）
        up = np.zeros_like(skin)
        up[: int(h * 0.6), :] = skin[: int(h * 0.6), :]
        findings += self._from_mask(up, (h, w), "no_helmet", min_area=0.0012)
        return findings

    @staticmethod
    def _from_mask(mask: np.ndarray, shape, ftype: str, min_area: float) -> List[dict]:
        h, w = shape
        total = h * w
        area = float(mask.sum())
        if area < min_area * total:
            return []
        ys, xs = np.where(mask)
        x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())
        frac = area / total
        conf = float(np.clip(0.6 + frac * 4.0, 0.6, 0.97))
        return [
            {
                "type": ftype,
                "label": _label_of(ftype),
                "confidence": round(conf, 3),
                "bbox": [x0, y0, x1 - x0, y1 - y0],
            }
        ]


class YoloDetector:
    """可插拔的真实模型检测器（生产替换用）。

    需要 ``pip install ultralytics`` 并提供权重；未安装时实例化即抛错，
    不影响 ReferenceDetector 作为默认路径。``detect`` 契约与 ReferenceDetector 一致。
    """

    name = "yolov8-rail"

    def __init__(self, weights: str | None = None):
        try:
            from ultralytics import YOLO
        except ImportError as exc:  # pragma: no cover - 依赖可选
            raise RuntimeError(
                "YoloDetector 需要 ultralytics（pip install ultralytics）与权重文件"
            ) from exc
        self._model = YOLO(weights or "yolov8n.pt")

    def detect(self, image: Image.Image) -> List[dict]:
        results = self._model.predict(image, verbose=False)
        findings: List[dict] = []
        for res in results:
            names = getattr(res, "names", {})
            for box in getattr(res, "boxes", []):
                cls = int(box.cls[0])
                name = names.get(cls, str(cls)).lower()
                ftype = self._map_class(name)
                if ftype is None:
                    continue
                x0, y0, x1, y1 = [int(v) for v in box.xyxy[0].tolist()]
                conf = float(box.conf[0])
                findings.append(
                    {
                        "type": ftype,
                        "label": _label_of(ftype),
                        "confidence": round(conf, 3),
                        "bbox": [x0, y0, x1 - x0, y1 - y0],
                    }
                )
        return findings

    @staticmethod
    def _map_class(name: str) -> str | None:
        if "fire" in name or "smoke" in name:
            return "smoke_fire"
        if "helmet" in name:
            return "other"
        if "person" in name:
            return "no_helmet"
        if "intrusion" in name:
            return "intrusion"
        return None


_DETECTORS: dict[str, type] = {
    "reference": ReferenceDetector,
    "default": ReferenceDetector,
    "yolo": YoloDetector,
    "yolov8": YoloDetector,
}


def get_detector(model: str = "default") -> Detector:
    """按 model 名解析检测器；未知名回退到 ReferenceDetector。"""
    cls = _DETECTORS.get((model or "default").lower(), ReferenceDetector)
    return cls()  # type: ignore[call-arg]


def analyze_payload(payload: dict) -> dict:
    """服务侧主入口：加载帧 → 检测 → 返回 {model, findings}。"""
    image = load_frame(payload)
    detector = get_detector(payload.get("model", "default"))
    findings = detector.detect(image) if image is not None else []
    return {"model": detector.name, "findings": findings}
