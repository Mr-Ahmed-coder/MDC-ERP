#!/bin/bash
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo ""
  echo "  [!] Python3 lama helin / not found."
  echo "      Ka soo deji / Download: https://www.python.org/downloads/"
  echo ""
  exit 1
fi
echo "  Diyaarinta koowaad... / First-time setup (may take a minute)..."
python3 -m venv venv 2>/dev/null
source venv/bin/activate
pip install -q -r requirements.txt
echo ""
echo "  =================================================="
echo "    Modern Diagnostic Center ERP - RUNNING"
echo "    Open browser: http://127.0.0.1:5000"
echo "    Login:  admin  /  password set during initialization"
echo "    To stop: press CTRL+C"
echo "  =================================================="
echo ""
( sleep 2; open http://127.0.0.1:5000 2>/dev/null || xdg-open http://127.0.0.1:5000 2>/dev/null ) &
python3 run.py "$@"
