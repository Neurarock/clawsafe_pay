#!/usr/bin/env bash
# ── ClawSafe Pay — One-Line Demo Launcher ─────────────────────────────────
#
# Usage:   ./demo.sh          (start all services + open dashboard)
#          ./demo.sh stop     (kill all services)
#
set -euo pipefail
cd "$(dirname "$0")"

PORT_AUTH=8000
PORT_SIGNER=8001
PORT_PUBLISHER=8002

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

banner() {
  echo ""
  echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════════╗${NC}"
  echo -e "${CYAN}${BOLD}║       🔐  ClawSafe Pay  — Demo Mode         ║${NC}"
  echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════════╝${NC}"
  echo ""
}

stop_services() {
  echo -e "${RED}Stopping services...${NC}"
  for port in $PORT_AUTH $PORT_SIGNER $PORT_PUBLISHER; do
    pids=$(lsof -iTCP:${port} -sTCP:LISTEN -t 2>/dev/null || true)
    if [[ -n "$pids" ]]; then
      kill $pids 2>/dev/null || true
      echo -e "  Killed port ${port}"
    fi
  done
  echo -e "${GREEN}All services stopped.${NC}"
}

if [[ "${1:-}" == "stop" ]]; then
  stop_services
  exit 0
fi

banner

# ── Activate venv ──────────────────────────────────────────────────────
if [[ -d .venv ]]; then
  source .venv/bin/activate
else
  echo -e "${RED}ERROR: .venv not found. Run: python3 -m venv .venv && pip install -r requirements.txt${NC}"
  exit 1
fi

# ── Stop any existing services ─────────────────────────────────────────
stop_services
sleep 1

# ── Start services in background ───────────────────────────────────────
echo -e "${CYAN}Starting services...${NC}"

python -m user_auth.main     > /tmp/clawsafe_user_auth.log 2>&1 &
echo -e "  ${GREEN}✓${NC} user_auth        → http://localhost:${PORT_AUTH}"

python -m signer_service.main > /tmp/clawsafe_signer.log 2>&1 &
echo -e "  ${GREEN}✓${NC} signer_service   → http://localhost:${PORT_SIGNER}"

python -m publisher_service.main > /tmp/clawsafe_publisher.log 2>&1 &
echo -e "  ${GREEN}✓${NC} publisher_service → http://localhost:${PORT_PUBLISHER}"

# ── Wait for health checks ────────────────────────────────────────────
echo ""
echo -ne "${CYAN}Waiting for services to be ready...${NC}"
for i in {1..20}; do
  sleep 1
  h1=$(curl -sf http://localhost:${PORT_AUTH}/health 2>/dev/null || true)
  h2=$(curl -sf http://localhost:${PORT_SIGNER}/health 2>/dev/null || true)
  h3=$(curl -sf http://localhost:${PORT_PUBLISHER}/health 2>/dev/null || true)
  if [[ -n "$h1" && -n "$h2" && -n "$h3" ]]; then
    echo -e " ${GREEN}Ready!${NC}"
    break
  fi
  echo -n "."
done

# ── Open dashboard ─────────────────────────────────────────────────────
DASHBOARD_URL="http://localhost:${PORT_PUBLISHER}/dashboard"
echo ""
echo -e "${BOLD}${GREEN}Dashboard: ${DASHBOARD_URL}${NC}"
echo -e "${CYAN}Logs:${NC}  /tmp/clawsafe_*.log"
echo ""
echo -e "${CYAN}To stop:  ${BOLD}./demo.sh stop${NC}"
echo ""

# Open in default browser (macOS / Linux)
if command -v open &>/dev/null; then
  open "$DASHBOARD_URL"
elif command -v xdg-open &>/dev/null; then
  xdg-open "$DASHBOARD_URL"
fi

# Keep script alive, stream publisher logs
echo -e "${CYAN}── Publisher log (Ctrl+C to detach) ──${NC}"
tail -f /tmp/clawsafe_publisher.log 2>/dev/null || true
