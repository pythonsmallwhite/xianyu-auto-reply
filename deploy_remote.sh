#!/usr/bin/env bash
# 闲鱼自动回复系统（自用 fork）
# 原版“远程 MySQL/Redis + 原作者预构建镜像”部署方式已移除：那些镜像不包含本仓库的改动（带广告）。
# 请在 Ubuntu 24.04 服务器上使用：bash deploy.sh   （从本仓库源码构建，内置 MySQL/Redis）
printf '[deploy_remote] 已移除：本 fork 只支持从源码构建部署，请执行 bash deploy.sh\n' >&2
exit 1
