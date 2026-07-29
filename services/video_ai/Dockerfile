# 视频 AI 参考推理服务镜像
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    VIDEO_AI_PORT=8900

WORKDIR /app

# 复制依赖清单并安装（利用层缓存）
COPY services/video_ai/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

# 复制服务代码
COPY services/ /app/services/

EXPOSE 8900

# 以模块方式启动，便于宿主机/compose 映射端口
CMD ["python", "-m", "uvicorn", "services.video_ai.app:app", "--host", "0.0.0.0", "--port", "8900"]
