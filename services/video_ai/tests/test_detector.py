"""ReferenceDetector 单元验证：确保真实像素分析在不同输入下行为正确。"""

from PIL import Image, ImageDraw

from services.video_ai.detector import (
    ReferenceDetector,
    analyze_payload,
    load_frame,
)


def _img_with_blob(blob_color, xy, size=80, bg=(28, 30, 34)):
    img = Image.new("RGB", (640, 480), bg)
    d = ImageDraw.Draw(img)
    d.ellipse([xy[0], xy[1], xy[0] + size, xy[1] + size], fill=blob_color)
    return img


def test_load_frame_demo():
    img = load_frame({"demo": True})
    assert isinstance(img, Image.Image)
    assert img.size == (640, 480)


def test_load_frame_base64_roundtrip():
    src = _img_with_blob((222, 44, 30), (300, 40))
    import base64
    import io

    buf = io.BytesIO()
    src.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    img = load_frame({"frame_b64": b64})
    assert isinstance(img, Image.Image)


def test_detect_smoke_fire():
    det = ReferenceDetector()
    img = _img_with_blob((222, 44, 30), (300, 40))  # 顶部红色火点
    findings = det.detect(img)
    types = {f["type"] for f in findings}
    assert "smoke_fire" in types
    for f in findings:
        assert 0 <= f["confidence"] <= 1
        assert len(f["bbox"]) == 4


def test_detect_intrusion_danger_zone():
    det = ReferenceDetector()
    img = _img_with_blob((205, 162, 132), (120, 400))  # 底部危险区肤色
    findings = det.detect(img)
    assert "intrusion" in {f["type"] for f in findings}


def test_detect_no_helmet_upper_zone():
    det = ReferenceDetector()
    img = _img_with_blob((205, 162, 132), (300, 60))  # 顶部肤色（无帽）
    findings = det.detect(img)
    assert "no_helmet" in {f["type"] for f in findings}


def test_analyze_payload_empty_without_frame():
    res = analyze_payload({"channel_no": "CAM-1"})
    assert res["model"] == "rail-reference-detector-v1"
    assert res["findings"] == []


def test_analyze_payload_demo_produces_findings():
    res = analyze_payload({"demo": True, "model": "default"})
    assert res["model"] == "rail-reference-detector-v1"
    assert len(res["findings"]) >= 1
