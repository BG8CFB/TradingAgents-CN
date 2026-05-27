#!/bin/bash
set -e

# Docker entrypoint: fix volume permissions then drop to appuser
#
# Volume-mounted directories (bind mount or named volume) may be owned by root
# when created by the host OS or a previous container. This script runs as root
# at startup, fixes ownership, then drops privileges to appuser before executing
# the application command.

if [ "$(id -u)" = "0" ]; then
    # Fix ownership of volume-mounted directories
    chown -R appuser:appuser /app/runtime /app/config 2>/dev/null || true

    # Drop to appuser and execute the command (CMD or docker-compose command)
    exec runuser -u appuser -- "$@"
fi

# Already running as non-root user — just execute the command
exec "$@"
