$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

# 本地开发：加载 .env.local（DJANGO_ENV=local）
$env:DJANGO_ENV = "local"

# DashScope API Key 兜底：项目读 DASHSCOPE_API_KEY，本机系统变量叫 ALIYUN_API_KEY
if (-not $env:DASHSCOPE_API_KEY) {
  $k = $env:ALIYUN_API_KEY
  if (-not $k) { $k = [Environment]::GetEnvironmentVariable('ALIYUN_API_KEY', 'User') }
  if ($k) { $env:DASHSCOPE_API_KEY = $k }
}

if (-not (Test-Path "$Root\.venv\Scripts\celery.exe")) {
  throw "未找到 .venv\Scripts\celery.exe，请先创建虚拟环境并安装依赖。"
}

# 消费 default 队列（CELERY_TASK_DEFAULT_QUEUE = "default"）
# -n 显式命名节点，避免与 vision worker 同名导致 inspect 误判
& "$Root\.venv\Scripts\celery.exe" -A __000__django worker -Q default -l info -P solo -n "worker-default@%h"

