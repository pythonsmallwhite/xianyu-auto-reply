#!/usr/bin/env bash
# 闲鱼自动回复系统（自用 fork）- 更新入口
# 原版本拉取原作者预构建镜像（带广告），已废弃；现在等同于 `bash deploy.sh update`：
# 用当前仓库源码构建镜像并更新，失败自动回滚。用法：git pull && bash update.sh
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
case "${1:-update}" in
  update) exec bash "$ROOT_DIR/deploy.sh" update ;;
  status|logs|rollback|backup) exec bash "$ROOT_DIR/deploy.sh" "$1" ;;
  help|-h|--help) sed -n '2,4p' "$0" | sed 's/^# \{0,1\}//' ;;
  *) printf '[update] ERROR: unsupported command %s (use: update|status|logs|rollback|backup)\n' "$1" >&2; exit 1 ;;
esac
