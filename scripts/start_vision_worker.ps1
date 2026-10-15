param(
  [int]$Concurrency = 1,
  [string]$LogLevel = "info"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$env:ENABLE_VISION_WORKER = "True"

# 本地开发：加载 .env.local（DJANGO_ENV=local）
$env:DJANGO_ENV = "local"

# DashScope API Key 兜底：项目读 DASHSCOPE_API_KEY，本机系统变量叫 ALIYUN_API_KEY
if (-not $env:DASHSCOPE_API_KEY) {
  $k = $env:ALIYUN_API_KEY
  if (-not $k) { $k = [Environment]::GetEnvironmentVariable('ALIYUN_API_KEY', 'User') }
  if ($k) { $env:DASHSCOPE_API_KEY = $k }
}

Write-Host "Starting VLM-RAG vision worker..."
Write-Host "This worker requires local Torch/Byaldi/ColPali dependencies and model files."

.\.venv\Scripts\celery.exe -A __000__django worker -Q vision -P solo -c $Concurrency -n "worker-vision@%h" --loglevel=$LogLevel
