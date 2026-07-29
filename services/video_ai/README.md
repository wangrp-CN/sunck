# 视频 AI 参考推理服务（⑧）

涉铁工程监控平台的**外部推理服务**参考实现。平台自身不做推理，由本服务完成
「主动下发分析任务 → 返回结构化异常 findings」的闭环（详见 `app/service/video_ai.py`）。

> 本实现是**可运行的参考检测器**，使用纯 Pillow + numpy 的像素级启发式，
> 不依赖训练模型，开箱即用。生产环境可将 `ReferenceDetector` 一键替换为
> 真实 YOLO 等模型（见下文「切换为真实模型」），服务契约不变。

## 契约（与平台对齐）

平台 `POST {VIDEO_AI_ENDPOINT}`，body：

```json
{ "payload": { "channel_no": "CAM-01", "frame_url": "http://.../f.jpg", "model": "default" } }
```

`payload` 帧来源（三选一，优先级递减）：

- `frame_url`：远程图片 URL（服务侧下载，超时 5s）
- `frame_b64`：base64 图片（支持 `data:image/...;base64,` 前缀）
- `demo: true`：合成测试帧（联调用，无需真实画面）

服务返回：

```json
{
  "model": "rail-reference-detector-v1",
  "findings": [
    { "type": "smoke_fire", "label": "烟火", "confidence": 0.91, "bbox": [300, 36, 92, 92] }
  ]
}
```

`findings` 为空数组表示「未识别到异常」。`type` ∈ `intrusion / no_helmet / smoke_fire / other`，
与平台 `VIDEO_AI_CAPABILITIES` 一致。

## 本地运行

```bash
cd rail_monitor
pip install -r services/video_ai/requirements.txt
python -m uvicorn services.video_ai.app:app --host 127.0.0.1 --port 8900
```

健康检查：`curl http://127.0.0.1:8900/health`
能力自描述：`curl http://127.0.0.1:8900/capabilities`

联调示例（demo 帧）：

```bash
curl -X POST http://127.0.0.1:8900/infer \
  -H 'Content-Type: application/json' \
  -d '{"payload":{"demo":true,"model":"default"}}'
```

## 测试

```bash
pip install pytest pillow numpy
python -m pytest services/video_ai/tests/ -q
```

## 部署

### systemd（推荐，与平台其它服务一致）

见 `deploy/rail-monitor-video-ai.service`：

```bash
cp deploy/rail-monitor-video-ai.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now rail-monitor-video-ai
```

### Docker

```bash
docker build -f services/video_ai/Dockerfile -t rail-video-ai .
docker run -d --name rail-video-ai -p 8900:8900 rail-video-ai
```

或 `docker compose -f deploy/docker-compose.video-ai.yml up -d`。

### 接入平台

1. 推理服务监听 `8900`。
2. 平台 `.env`：`VIDEO_AI_ENABLED=true`、`VIDEO_AI_ENDPOINT=http://127.0.0.1:8900/infer`。
   生产经 nginx 反代则为 `https://<域名>/ai/infer`（见 `deploy/nginx.conf` 的 `/ai/` 位置）。
3. 重启平台，`POST /api/v1/videos/ai/analyze` 即返回 `status=done` + `findings`。

## 切换为真实模型（YOLO 等）

`detector.py` 已预留 `YoloDetector` 接口，契约与 `ReferenceDetector` 完全一致：

1. `pip install ultralytics`，准备权重（如 `yolov8n.pt` 或自训铁路安全模型）。
2. 下发时 `payload.model = "yolo"`（或设置服务默认检测器）。
3. `YoloDetector.detect` 将运行真实模型并返回同类 `findings`，平台无需任何改动。

> 生产精度取决于模型质量；参考检测器仅用于打通链路与演示。
