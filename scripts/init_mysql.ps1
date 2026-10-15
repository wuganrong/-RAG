param(
  [string]$HostName = "127.0.0.1",
  [string]$Port = "3306",
  [string]$User = "root",
  [string]$Database = "yf_vision_rag",
  [switch]$SeedOnly
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if (-not (Get-Command mysql -ErrorAction SilentlyContinue)) {
  throw "未找到 mysql 命令，请先安装 MySQL Client 或手动执行 data\init 下 SQL。"
}

if (-not (Test-Path ".env") -and (Test-Path "data\init\.env.mysql.example")) {
  Copy-Item "data\init\.env.mysql.example" ".env"
  Write-Host "已创建 .env（MySQL 模板），请确认密码和连接信息。"
}

if (-not $SeedOnly) {
  Get-Content "data\init\mysql_create_database.sql" -Raw | mysql -h $HostName -P $Port -u $User -p --default-character-set=utf8mb4
  $env:DB_ENGINE = "mysql"
  python manage.py migrate
}

Get-Content "data\init\mysql_seed.sql" -Raw | mysql -h $HostName -P $Port -u $User -p --default-character-set=utf8mb4 $Database
Write-Host "MySQL 初始化完成：$Database"
