"""pytest 公共夹具（骨架）。"""

from app.config import settings

# 测试环境默认关闭登录验证码，避免影响现有登录用例；
# 验证码专项测试（test_captcha.py）会临时开启并自行恢复。
settings.captcha_enabled = False
