#!/usr/bin/env pwsh
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw '未找到 uv，请先安装后再运行。'
}

if (-not (Test-Path 'backend/.env')) {
    Copy-Item 'backend/.env.example' 'backend/.env'
    Write-Host '已创建 backend/.env，请填写 OPENAI_API_KEY 后重新运行。' -ForegroundColor Yellow
}

Set-Location backend
uv sync
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
