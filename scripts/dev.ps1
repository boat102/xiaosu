#!/usr/bin/env pwsh
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

foreach ($cmd in @('uv', 'pnpm')) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        throw "未找到 $cmd，请先安装后再运行。"
    }
}

if (-not (Test-Path 'backend/.env')) {
    Copy-Item 'backend/.env.example' 'backend/.env'
    Write-Host '已创建 backend/.env，请填写 OPENAI_API_KEY 后重新运行。' -ForegroundColor Yellow
}
if (-not (Test-Path 'frontend/.env.local')) {
    Copy-Item 'frontend/.env.example' 'frontend/.env.local'
}

Push-Location backend
uv sync
Pop-Location

Push-Location frontend
pnpm install
Pop-Location

$shell = if (Get-Command pwsh -ErrorAction SilentlyContinue) { 'pwsh' } else { 'powershell' }
Start-Process $shell -ArgumentList @('-NoExit', '-Command', "Set-Location '$root\backend'; uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000")
Start-Process $shell -ArgumentList @('-NoExit', '-Command', "Set-Location '$root\frontend'; pnpm dev")

Write-Host '后端 http://127.0.0.1:8000/docs   前端 http://localhost:3000' -ForegroundColor Green
