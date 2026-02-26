#!/bin/bash
# Start both the FastAPI backend and Next.js frontend for local development.
# Usage: ./dev.sh
#
# Backend:  http://localhost:8000  (FastAPI + REST API + WebSocket)
# Frontend: http://localhost:3000  (Next.js dashboard, proxies /api/* to backend)
#
# Press Ctrl+C to stop both.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WEBUI_DIR="$SCRIPT_DIR/webui"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

cleanup() {
    echo ""
    echo -e "${YELLOW}Shutting down...${NC}"
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null
    wait $BACKEND_PID $FRONTEND_PID 2>/dev/null
    echo -e "${GREEN}Done.${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM

# Check dependencies
if ! command -v python &>/dev/null; then
    echo "Error: python not found. Install Python 3.11+."
    exit 1
fi

if ! command -v node &>/dev/null; then
    echo "Error: node not found. Install Node.js 18+."
    exit 1
fi

# Install frontend deps if needed
if [ ! -x "$WEBUI_DIR/node_modules/.bin/next" ]; then
    echo -e "${BLUE}Installing frontend dependencies...${NC}"
    (cd "$WEBUI_DIR" && npm install)
fi

echo -e "${GREEN}Starting Code Autonomy...${NC}"
echo ""

# Start backend (no pipe — avoids buffering issues)
echo -e "${BLUE}[Backend]${NC}  http://localhost:8000"
uvicorn src.api.app:app --reload --port 8000 --host 0.0.0.0 &
BACKEND_PID=$!

# Start frontend
echo -e "${BLUE}[Frontend]${NC} http://localhost:3000"
(cd "$WEBUI_DIR" && ./node_modules/.bin/next dev --port 3000) &
FRONTEND_PID=$!

echo ""
echo -e "${GREEN}Both services running. Press Ctrl+C to stop.${NC}"
echo ""

# Wait for either to exit
wait $BACKEND_PID $FRONTEND_PID
