#!/usr/bin/env pwsh
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location "$root\backend"

if (-not (Test-Path '.env')) {
    throw '缺少 backend/.env，请先复制 .env.example 并填写钉钉凭证。'
}

uv run python -m app.dingtalk_bot
