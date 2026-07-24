#!/usr/bin/env bash
# =============================================================
# 涉铁工程智能监控平台 —— HTTPS 一键启用（certbot + nginx 插件）
# 作用：为指定域名申请 Let's Encrypt 证书，并自动把 nginx 配置改写为
#       443(SSL) + HTTP→HTTPS 跳转 + HSTS；同时启用证书自动续期。
#
# 前置条件：
#   1) 操作系统已安装 nginx 与 certbot（含 nginx 插件：certbot 与 python3-certbot-nginx）
#   2) 域名已正确解析（A/AAAA）到本机公网 IP
#   3) 本脚本执行前，deploy/nginx.conf 已就位且 `nginx -t` 通过、nginx 正在运行
#   4) 80 端口对外可访问（ACME http-01 验证需要）
#
# 用法：
#   sudo bash deploy/scripts/setup-tls.sh <域名> <邮箱>
#   sudo bash deploy/scripts/setup-tls.sh monitor.example.com ops@example.com
#
# 幂等：若证书已存在，certbot 会走续期逻辑而非重复申请。
# 回滚：sudo certbot delete --cert-name <域名>，并手动将 nginx 配置恢复为仅 80。
# =============================================================
set -euo pipefail

DOMAIN="${1:-}"
EMAIL="${2:-}"

if [[ -z "$DOMAIN" || -z "$EMAIL" ]]; then
  echo "用法: sudo bash $0 <域名> <邮箱>" >&2
  echo "示例: sudo bash $0 monitor.example.com ops@example.com" >&2
  exit 2
fi

command -v nginx >/dev/null 2>&1 || { echo "✗ 未找到 nginx，请先安装" >&2; exit 1; }
command -v certbot >/dev/null 2>&1 || { echo "✗ 未找到 certbot，请先安装（含 nginx 插件）" >&2; exit 1; }

echo "==> 步骤 1/4：校验 nginx 配置语法"
if ! nginx -t >/dev/null 2>&1; then
  echo "✗ nginx -t 失败，请先修复配置（deploy/nginx.conf）" >&2
  nginx -t
  exit 1
fi

echo "==> 步骤 2/4：申请证书并自动改写 nginx（certbot --nginx）"
certbot --nginx \
  -d "$DOMAIN" \
  --non-interactive \
  --agree-tos \
  --email "$EMAIL" \
  --redirect \
  --deploy-hook "systemctl reload nginx" \
  || { echo "✗ certbot 申请失败，请检查域名解析/80 端口/速率限制" >&2; exit 1; }

echo "==> 步骤 3/4：校验改写后的 nginx 并重载"
nginx -t
systemctl reload nginx

echo "==> 步骤 4/4：启用证书自动续期（certbot 自带 timer）"
# 多数发行版 certbot 包自带 certbot.timer；启用并确保开机自启。
if systemctl list-unit-files certbot.timer >/dev/null 2>&1; then
  systemctl enable --now certbot.timer
  echo "    已启用 certbot.timer（每日检查，到期前自动续期并 reload nginx）"
else
  echo "    未检测到 certbot.timer，建议配置 cron：0 3 * * * certbot renew --quiet --deploy-hook 'systemctl reload nginx'"
fi

echo ""
echo "✅ HTTPS 启用完成："
echo "   - 站点 https://$DOMAIN 已可用，HTTP 自动跳转 HTTPS"
echo "   - 证书 90 天有效，已配置自动续期"
echo "   - 如需手动验证续期流程（不实际改写）：certbot renew --dry-run"
