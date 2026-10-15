#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="8111"
DB_FILE="$ROOT_DIR/smoke_test.db"
cd "$ROOT_DIR"
export APP_DATABASE_URL="sqlite:///./smoke_test.db"

rm -f "$DB_FILE"

python -m uvicorn main:app --host 127.0.0.1 --port "$PORT" > "$ROOT_DIR/smoke_test_server.log" 2>&1 &
SERVER_PID=$!
cleanup() {
  kill "$SERVER_PID" 2>/dev/null || true
  wait "$SERVER_PID" 2>/dev/null || true
  rm -f "$DB_FILE" "$ROOT_DIR/smoke_test_server.log"
}
trap cleanup EXIT

for _ in {1..30}; do
  if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null; then
    break
  fi
  sleep 1
done

health_response="$(curl -fsS "http://127.0.0.1:$PORT/health")"
python -c 'import json, sys; data=json.loads(sys.argv[1]); assert data["db"] == "ok"' "$health_response"

for message in "hello" "good morning" "good night"; do
  response="$(curl -fsS -X POST "http://127.0.0.1:$PORT/chat" -H "Content-Type: application/json" -d "{\"message\":\"$message\"}")"
  python -c 'import json, sys; data=json.loads(sys.argv[1]); assert data.get("reply")' "$response"
done

message_count="$(python -c 'import sqlite3; db=sqlite3.connect("smoke_test.db"); print(db.execute("SELECT COUNT(*) FROM chat_message").fetchone()[0])')"
if [[ "$message_count" != "6" ]]; then
  echo "FAIL: expected 6 messages, got $message_count"
  exit 1
fi

echo "PASS"
