#!/usr/bin/env bash
# Start the user-local MongoDB 8.0.4 instance used by the Smart Campus system.
# No root required; data lives under ~/.local/share/scms-mongo.
set -euo pipefail

MONGO_HOME="${MONGO_HOME:-/tmp/mongodb-linux-x86_64-ubuntu2204-8.0.4}"
STATE_DIR="${SCMS_MONGO_STATE:-$HOME/.local/share/scms-mongo}"
DATA_DIR="$STATE_DIR/data"
LOG_DIR="$STATE_DIR/log"
PORT="${SCMS_MONGO_PORT:-27017}"

mkdir -p "$DATA_DIR" "$LOG_DIR"

if "$MONGO_HOME/bin/mongod" --version >/dev/null 2>&1; then
  echo "mongod binary: OK"
else
  echo "mongod binary missing at $MONGO_HOME/bin/mongod" >&2
  exit 1
fi

if "$MONGO_HOME/bin/mongod" --dbpath "$DATA_DIR" --port "$PORT" --bind_ip 127.0.0.1 \
   --fork --logpath "$LOG_DIR/mongod.log" >/dev/null 2>&1; then
  echo "mongod started on 127.0.0.1:$PORT (dbpath=$DATA_DIR)"
else
  if tail -n 5 "$LOG_DIR/mongod.log" | grep -qi "already running\|address already in use"; then
    echo "mongod already running on port $PORT"
  else
    echo "mongod failed to start; last log lines:" >&2
    tail -n 20 "$LOG_DIR/mongod.log" >&2
    exit 1
  fi
fi
