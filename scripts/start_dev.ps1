param(
  [string]$HostName = "127.0.0.1",
  [string]$Port = "9380"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

# 本地开发模式：加载 .env.local（数据库/Redis/MinIO/ES 全部指向本机 Docker）
$env:DJANGO_ENV = "local"

# DashScope API Key 兜底：项目读 DASHSCOPE_API_KEY，本机系统变量叫 ALIYUN_API_KEY
if (-not $env:DASHSCOPE_API_KEY) {
  $k = $env:ALIYUN_API_KEY
  if (-not $k) { $k = [Environment]::GetEnvironmentVariable('ALIYUN_API_KEY', 'User') }
  if ($k) { $env:DASHSCOPE_API_KEY = $k }
}
if (-not $env:DASHSCOPE_BASE_URL) {
  $env:DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
}

if (-not (Test-Path "$Root\.venv\Scripts\python.exe")) {
  throw "未找到 .venv，请先创建虚拟环境：uv venv --python 3.12 .venv"
}

& "$Root\.venv\Scripts\python.exe" manage.py runserver "$HostName`:$Port"
