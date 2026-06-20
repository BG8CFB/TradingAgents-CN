#!/bin/bash
set -e

# Docker entrypoint: fix volume permissions then drop to appuser
#
# Volume-mounted directories (bind mount or named volume) may be owned by root
# when created by the host OS or a previous container. This script runs as root
# at startup, fixes ownership, prints first-run guidance, then drops privileges
# to appuser before executing the application command.

# ── 首次启动配置检测日志（仅 root 阶段打印，便于排查） ──
if [ -z "$JWT_SECRET" ] && [ -z "$CSRF_SECRET" ]; then
    echo "═══════════════════════════════════════════════════════════"
    echo "  ℹ️  Security secrets not provided via environment"
    echo "      SecretService will auto-generate and persist them on first start."
    echo "      To customize, create a .env file in the deploy directory."
    echo "      Template: deploy/.env.example"
    echo "═══════════════════════════════════════════════════════════"
fi

if [ -n "$INITIAL_ADMIN_PASSWORD" ] && [ "$INITIAL_ADMIN_PASSWORD" = "admin123" ]; then
    echo "  ⚠️  Using default admin password 'admin123' — change it immediately after first login."
fi

if [ "$(id -u)" = "0" ]; then
    # Fix ownership of volume-mounted directories
    chown -R appuser:appuser /app/runtime /app/config 2>/dev/null || true

    # Drop to appuser and execute the command (CMD or docker-compose command)
    exec runuser -u appuser -- "$@"
fi

# Already running as non-root user — just execute the command
exec "$@"
