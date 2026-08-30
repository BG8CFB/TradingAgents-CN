#!/usr/bin/env bash
# NAS 源码热同步 — 本地 → NAS 快速更新通道（配合 docker-compose.hub.dev.yml）
#
# 用途：把本地 app/ 与 frontend/dist 同步到 NAS 部署目录的 src/ 下，
#   backend 由 uvicorn --reload 秒级热重载，frontend 由 nginx 直接生效，全程不停容器。
#
# 用法：
#   bash scripts/sync_nas.sh                    # 前端重新构建 + 后端/前端全量同步
#   SYNC_FRONTEND=0 bash scripts/sync_nas.sh    # 只同步后端代码
#   SYNC_BACKEND=0 SKIP_BUILD=1 bash scripts/sync_nas.sh  # 只推已构建的前端产物
#
# 环境变量：
#   NAS_HOST      SSH 别名（~/.ssh/config），默认 NAS
#   NAS_DIR       NAS 部署目录，默认 /vol1/1000/System/DockerYml/TradingAgents-CN
#   SYNC_BACKEND  1=同步后端（默认）
#   SYNC_FRONTEND 1=同步前端（默认）
#   SKIP_BUILD    1=跳过本地 npm run build（仅在确信 dist 是最新时使用）
#
# 传输方式：本地 tar-over-ssh（Git Bash 无 rsync）落 staging，NAS 端 rsync
#   文件级镜像替换（--delete 清理本地已删除的文件，避免陈旧 .py / 旧 chunk 残留）。
#   关键约束：绝不能 rename/替换目标目录本身 —— uvicorn --reload 的 inotify
#   监听绑在目录 inode 上，rename 目录会让 watch 静默断裂（实测卡死：
#   WatchFiles 报一批变化后 import 失败，此后任何文件变化都不再触发 reload）。
set -euo pipefail

NAS_HOST="${NAS_HOST:-NAS}"
NAS_DIR="${NAS_DIR:-/vol1/1000/System/DockerYml/TradingAgents-CN}"
SYNC_BACKEND="${SYNC_BACKEND:-1}"
SYNC_FRONTEND="${SYNC_FRONTEND:-1}"
SKIP_BUILD="${SKIP_BUILD:-0}"

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# 远端镜像式同步：staging 解压 → chmod 保证容器 appuser 可读 → rsync 文件级替换
# 用法：_sync_dir <本地源目录> <NAS 目标目录（绝对路径）> <收尾 touch 文件（可空）>
_sync_dir() {
  local local_src="$1"
  local remote_dst="$2"
  local touch_file="${3:-}"

  ssh "$NAS_HOST" "rm -rf '${remote_dst}.staging' && mkdir -p '${remote_dst}.staging'"
  tar -czf - -C "$local_src" \
    --exclude='__pycache__' --exclude='*.pyc' --exclude='.pytest_cache' . \
    | ssh "$NAS_HOST" "tar -xzf - -C '${remote_dst}.staging'"
  ssh "$NAS_HOST" "
    chmod -R u+rwX,go+rX '${remote_dst}.staging' &&
    mkdir -p '${remote_dst}' &&
    rsync -a --delete '${remote_dst}.staging/' '${remote_dst}/' &&
    rm -rf '${remote_dst}.staging'
  "
  # 收尾显式 touch：rsync 过程中的事件可能触发 reload 撞上中间态，
  # 保证最后一次 watch 事件发生在目录完整时，reloader 用完整状态重启
  if [[ -n "$touch_file" ]]; then
    ssh "$NAS_HOST" "sleep 1 && touch '${remote_dst}/${touch_file}'"
  fi
}

if [[ "$SYNC_FRONTEND" == "1" ]]; then
  if [[ "$SKIP_BUILD" != "1" ]]; then
    echo "==> 构建前端产物..."
    (cd "$PROJECT_ROOT/frontend" && npm run build)
  fi
  if [[ ! -f "$PROJECT_ROOT/frontend/dist/index.html" ]]; then
    echo "错误：frontend/dist/index.html 不存在（构建失败或被跳过）" >&2
    exit 1
  fi
fi

ssh "$NAS_HOST" "mkdir -p '$NAS_DIR/src'"

if [[ "$SYNC_BACKEND" == "1" ]]; then
  echo "==> 同步后端 app/ ..."
  _sync_dir "$PROJECT_ROOT/app" "$NAS_DIR/src/app" "main.py"
fi

if [[ "$SYNC_FRONTEND" == "1" ]]; then
  echo "==> 同步前端 dist/ ..."
  _sync_dir "$PROJECT_ROOT/frontend/dist" "$NAS_DIR/src/frontend-dist"
fi

echo "==> 同步完成"
echo "    backend 由 uvicorn --reload 自动重载；frontend 经 nginx 直接生效"
echo "    首次启用或改动了覆盖层文件时，需在 NAS 上执行："
echo "    docker compose -f docker-compose.hub.nginx.yml -f docker-compose.hub.dev.yml up -d backend frontend"
