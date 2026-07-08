#!/usr/bin/env bash
#
# Turnkey local harness for the self-serve onboarding walkthrough.
#
# Starts the pieces the real funnel needs in the topology that actually works:
# Postgres + Redis in Docker, and the fake provider + backend + frontend on the
# host (the backend must reach the fake provider at 127.0.0.1:9100, which a
# container cannot). You still click through Auth0 + the wizard yourself -- that
# is the point of testing self-serve -- but everything around it is one command.
#
#   scripts/walkthrough.sh up             # bring up db, migrate, fake provider, backend, frontend
#   scripts/walkthrough.sh up --no-frontend
#   scripts/walkthrough.sh traffic --seed # generate live traffic (see walkthrough_traffic.py)
#   scripts/walkthrough.sh status
#   scripts/walkthrough.sh down           # stop host processes; keep the db
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
RUN="$ROOT/.walkthrough"
mkdir -p "$RUN"

FAKE_PROVIDER_URL="http://127.0.0.1:9100/v1/models"
API_URL="http://localhost:8000/health"
FRONTEND_URL="http://localhost:3000"

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
info() { printf '  %s\n' "$1"; }

require_venv() {
  if [ ! -x "$BACKEND/.venv/bin/python" ]; then
    echo "Backend venv not found at backend/.venv. Run: (cd backend && uv sync)" >&2
    exit 1
  fi
}

wait_http() {
  # wait_http <url> <label> <attempts>
  local url="$1" label="$2" attempts="${3:-60}"
  for _ in $(seq 1 "$attempts"); do
    if curl -fsS -o /dev/null "$url" 2>/dev/null; then
      info "$label is up"
      return 0
    fi
    sleep 1
  done
  echo "Timed out waiting for $label ($url)" >&2
  return 1
}

start_bg() {
  # start_bg <name> <logfile> <command...>
  local name="$1" log="$2"
  shift 2
  ( cd "$BACKEND" && exec "$@" ) >"$log" 2>&1 &
  echo $! >"$RUN/$name.pid"
  info "$name started (pid $(cat "$RUN/$name.pid"), logs: ${log#$ROOT/})"
}

stop_bg() {
  local name="$1" pidfile="$RUN/$1.pid"
  [ -f "$pidfile" ] || return 0
  local pid
  pid="$(cat "$pidfile")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    info "stopped $name (pid $pid)"
  fi
  rm -f "$pidfile"
}

cmd_up() {
  local with_frontend=1
  [ "${1:-}" = "--no-frontend" ] && with_frontend=0
  require_venv

  bold "1/5  Postgres + Redis (Docker)"
  docker compose -f "$ROOT/docker-compose.yml" up -d db redis
  for _ in $(seq 1 60); do
    if docker compose -f "$ROOT/docker-compose.yml" exec -T db pg_isready -U varsten -d varsten >/dev/null 2>&1; then
      info "database is ready"; break
    fi
    sleep 1
  done

  bold "2/5  Migrations"
  ( cd "$BACKEND" && .venv/bin/alembic upgrade head )

  bold "3/5  Fake provider (zero-cost OpenAI stub)"
  start_bg fake_provider "$RUN/fake_provider.log" .venv/bin/python scripts/fake_provider.py
  wait_http "$FAKE_PROVIDER_URL" "fake provider" 30

  bold "4/5  Backend API (host, so it can reach the fake provider)"
  start_bg backend "$RUN/backend.log" .venv/bin/uvicorn app.main:app --port 8000
  wait_http "$API_URL" "backend" 60

  if [ "$with_frontend" = 1 ]; then
    bold "5/5  Frontend (Next.js dev)"
    if [ ! -d "$FRONTEND/node_modules" ]; then
      echo "frontend/node_modules missing. Run: (cd frontend && npm install)" >&2
      exit 1
    fi
    ( cd "$FRONTEND" && exec npm run dev ) >"$RUN/frontend.log" 2>&1 &
    echo $! >"$RUN/frontend.pid"
    info "frontend started (pid $(cat "$RUN/frontend.pid"), logs: .walkthrough/frontend.log)"
    wait_http "$FRONTEND_URL" "frontend" 120 || info "frontend still compiling; check .walkthrough/frontend.log"
  else
    bold "5/5  Frontend skipped (--no-frontend)"
  fi

  echo
  bold "Ready. Walk the funnel:"
  info "Trial (Optimize):      http://localhost:3000/start?intent=trial"
  info "Observe (Free):        http://localhost:3000/start?intent=observe"
  info "Log in via Auth0, pick a connection path, create a key, and connect a"
  info "provider with any string (e.g. sk-fake-local-test — the stub accepts it)."
  echo
  bold "Then light up the dashboard with live traffic:"
  info "scripts/walkthrough.sh traffic --key vk_...     # the key from the wizard"
  info "scripts/walkthrough.sh traffic --seed           # or a throwaway key, no UI"
  info "(run 'make sync-prices' once so savings render priced)"
  echo
  info "Stop everything with: scripts/walkthrough.sh down"
}

cmd_traffic() {
  require_venv
  ( cd "$BACKEND" && .venv/bin/python scripts/walkthrough_traffic.py "$@" )
}

cmd_status() {
  for entry in "fake provider|$FAKE_PROVIDER_URL" "backend|$API_URL" "frontend|$FRONTEND_URL"; do
    local label="${entry%%|*}" url="${entry##*|}"
    if curl -fsS -o /dev/null "$url" 2>/dev/null; then
      printf '  \033[32m●\033[0m %s\n' "$label"
    else
      printf '  \033[31m○\033[0m %s (down)\n' "$label"
    fi
  done
}

cmd_down() {
  stop_bg frontend
  stop_bg backend
  stop_bg fake_provider
  info "database + redis left running (stop with: docker compose stop db redis)"
}

case "${1:-}" in
  up)      shift; cmd_up "$@" ;;
  traffic) shift; cmd_traffic "$@" ;;
  status)  cmd_status ;;
  down)    cmd_down ;;
  *)
    echo "usage: scripts/walkthrough.sh {up [--no-frontend] | traffic <args> | status | down}" >&2
    exit 2
    ;;
esac
