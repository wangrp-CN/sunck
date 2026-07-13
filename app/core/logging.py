"""日志配置：统一格式与级别，供应用启动时调用。"""

import logging
import sys

from app.config import settings

_CONFIGURED = False


def configure_logging(level: str | None = None) -> None:
    """配置根日志。重复调用幂等。"""
    global _CONFIGURED
    if _CONFIGURED:
        return
    lvl = (level or settings.log_level or "INFO").upper()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(lvl)
    # 第三方库降噪
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    _CONFIGURED = True
