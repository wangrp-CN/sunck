"""项目级 __main__ 入口（兜底方案）。

允许以 ``python <rail_monitor_dir>`` 方式直接启动服务。
PyCharm 某些运行配置模式会把目录当作模块执行（即调用本文件），
此时自动转发给 uvicorn。

正常方式仍推荐通过 uvicorn 直接启动：
  .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
"""

import os
import sys

# 确保当前目录在 sys.path 中（无论工作目录从哪里进来）
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)


def main():
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    main()
