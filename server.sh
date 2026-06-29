#!/usr/bin/env bash
# Start (or restart) the Kobie backend + frontend dev servers.
# Usage:
#   ./server.sh          — start both servers
#   ./server.sh restart  — kill existing processes and restart
#   ./server.sh stop     — kill existing processes and exit

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PID_FILE="$ROOT/.backend.pid"
FRONTEND_PID_FILE="$ROOT/.frontend.pid"
BACKEND_LOG="$ROOT/logs/backend.log"
FRONTEND_LOG="$ROOT/logs/frontend.log"

mkdir -p "$ROOT/logs"

kill_pid_file() {
  local pid_file="$1"
  local label="$2"
  if [[ -f "$pid_file" ]]; then
    local pid
    pid=$(cat "$pid_file")
    if kill -0 "$pid" 2>/dev/null; then
      echo "Stopping $label (pid $pid)..."
      kill "$pid"
      # Wait up to 5s for clean exit
      for i in $(seq 1 10); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.5
      done
      # Force kill if still alive
      kill -0 "$pid" 2>/dev/null && kill -9 "$pid" || true
    fi
    rm -f "$pid_file"
  fi
}

stop_all() {
  kill_pid_file "$BACKEND_PID_FILE" "backend"
  kill_pid_file "$FRONTEND_PID_FILE" "frontend"
}

check_and_repair_db() {
  local db="$ROOT/kobie.sqlite3"
  if [[ ! -f "$db" ]]; then return; fi
  local check
  check=$(sqlite3 "$db" "PRAGMA integrity_check;" 2>&1 | head -1)
  if [[ "$check" != "ok" ]]; then
    echo "WARNING: SQLite database is corrupt ($check). Moving aside and creating fresh DB..."
    mkdir -p "$ROOT/db_corrupted_backup"
    local ts; ts=$(date +%Y%m%d_%H%M%S)
    for f in "$ROOT"/kobie.sqlite3*; do
      [[ -f "$f" ]] && mv "$f" "$ROOT/db_corrupted_backup/$(basename "$f").$ts"
    done
    "$ROOT/.venv/bin/python" -c "from core.db import connect, migrate; migrate(connect())"
    echo "Fresh database created."
  fi
}

start_backend() {
  check_and_repair_db
  echo "Starting FastAPI backend on http://127.0.0.1:8001 ..."
  cd "$ROOT"
  uvicorn server:app --host 127.0.0.1 --port 8001 --reload \
    >> "$BACKEND_LOG" 2>&1 &
  echo $! > "$BACKEND_PID_FILE"
  echo "  backend pid: $(cat "$BACKEND_PID_FILE")  (log: logs/backend.log)"
}

start_frontend() {
  echo "Starting Next.js frontend on http://localhost:3000 ..."
  cd "$ROOT/frontend"
  npm run dev >> "$FRONTEND_LOG" 2>&1 &
  echo $! > "$FRONTEND_PID_FILE"
  echo "  frontend pid: $(cat "$FRONTEND_PID_FILE")  (log: logs/frontend.log)"
}

case "${1:-start}" in
  stop)
    stop_all
    echo "All servers stopped."
    ;;
  restart)
    stop_all
    sleep 1
    start_backend
    start_frontend
    echo ""
    echo "Servers restarted. Press Ctrl+C to tail logs (servers keep running on exit)."
    tail -f "$BACKEND_LOG" "$FRONTEND_LOG"
    ;;
  start)
    # Warn if already running
    if [[ -f "$BACKEND_PID_FILE" ]] && kill -0 "$(cat "$BACKEND_PID_FILE")" 2>/dev/null; then
      echo "Backend is already running (pid $(cat "$BACKEND_PID_FILE")). Use './server.sh restart' to restart."
      exit 1
    fi
    start_backend
    start_frontend
    echo ""
    echo "Servers started. Press Ctrl+C to tail logs (servers keep running on exit)."
    tail -f "$BACKEND_LOG" "$FRONTEND_LOG"
    ;;
  *)
    echo "Usage: $0 [start|stop|restart]"
    exit 1
    ;;
esac
