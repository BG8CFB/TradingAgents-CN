#!/usr/bin/env bash
# 本地全量测试预检脚本 —— 打 tag（触发 Docker Publish）前使用
#
# 与 CI (.github/workflows/ci.yml) 等价：
#   1. 启动 MongoDB/Redis 容器（若未运行）
#   2. unit 层：全量测试（不含 integration/slow/ai），单测超时 120s
#   3. integration 层：仅 integration 标记，单测超时 180s
#
# 用法（Git Bash / WSL / Linux，需已激活 tradingagents conda 环境）：
#   bash scripts/run_full_tests.sh
#
# 退出码：0 = 全部通过，适合 tag；1 = 有失败，先修复再 tag。

set -uo pipefail

cd "$(dirname "$0")/.."

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
fail=0

# 必须在 conda 环境 tradingagents 中运行
if [[ "${CONDA_DEFAULT_ENV:-}" != "tradingagents" ]]; then
    echo -e "${RED}[预检] 未激活 tradingagents conda 环境（当前: ${CONDA_DEFAULT_ENV:-无}）${NC}"
    echo "请先执行: conda activate tradingagents"
    exit 1
fi

echo "[预检] Python: $(python --version) @ $(which python)"

# pytest-timeout 为 CI 防挂起依赖，本地缺失时补装（幂等）
python -c "import pytest_timeout" 2>/dev/null || pip install -q pytest-timeout

# 1. 确保 MongoDB/Redis 容器运行（integration 层需要；unit 层不依赖）
echo "[预检] 启动 MongoDB/Redis 容器..."
docker compose -f docker-compose.dev.yml up -d mongodb redis

echo "[预检] 等待容器健康检查..."
for i in $(seq 1 30); do
    unhealthy=$(docker ps --filter "name=tradingagents-mongodb" --filter "name=tradingagents-redis" \
        --filter "health=healthy" --format '{{.Names}}' | wc -l)
    [[ "$unhealthy" -eq 2 ]] && break
    sleep 2
done

# 2. unit 层（与 CI unit job 相同参数；容器在跑也不影响，DB 测试有 sim 降级）
echo -e "${YELLOW}========== [1/2] unit 层 ==========${NC}"
python -m pytest tests/ -m "not integration and not slow and not ai" \
    --tb=short --durations=20 --timeout=120 -q -p no:cacheprovider
[[ $? -ne 0 ]] && fail=1

# 3. integration 层（与 CI integration job 相同参数）
echo -e "${YELLOW}========== [2/2] integration 层 ==========${NC}"
python -m pytest tests/ -m "integration and not ai" \
    --tb=short --durations=20 --timeout=180 -q -p no:cacheprovider
[[ $? -ne 0 ]] && fail=1

echo ""
if [[ $fail -eq 0 ]]; then
    echo -e "${GREEN}========== 预检通过，可以打 tag ==========${NC}"
    echo "建议流程: git tag vX.Y.Z && git push origin vX.Y.Z"
else
    echo -e "${RED}========== 预检未通过，请先修复失败项 ==========${NC}"
fi
exit $fail
