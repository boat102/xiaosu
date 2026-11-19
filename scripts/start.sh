#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ ! -f backend/.env ]]; then cp backend/.env.example backend/.env; echo "已创建 backend/.env，请先填写 OPENAI_API_KEY。"; fi
if [[ ! -f frontend/.env.local ]]; then cp frontend/.env.example frontend/.env.local; fi
cd backend
uv sync
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
