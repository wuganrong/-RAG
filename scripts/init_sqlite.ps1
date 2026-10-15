param(
  [switch]$SeedOnly
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if (-not (Test-Path ".env") -and (Test-Path "data\init\.env.sqlite.example")) {
  Copy-Item "data\init\.env.sqlite.example" ".env"
  Write-Host "已创建 .env（SQLite 模板）"
}

$env:DB_ENGINE = "sqlite"

if (-not $SeedOnly) {
  python manage.py migrate
}

$db = Join-Path $Root "data\yf_vision_rag.sqlite3"
if (Get-Command sqlite3 -ErrorAction SilentlyContinue) {
  sqlite3 $db ".read data/init/sqlite_seed.sql"
} else {
  python -c "import sqlite3; from pathlib import Path; root=Path.cwd(); db=root/'data'/'yf_vision_rag.sqlite3'; sql=(root/'data'/'init'/'sqlite_seed.sql').read_text(encoding='utf-8'); conn=sqlite3.connect(db); conn.executescript(sql); conn.commit(); conn.close()"
}

Write-Host "SQLite 初始化完成：data\yf_vision_rag.sqlite3"
