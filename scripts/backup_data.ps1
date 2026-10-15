param(
  [string]$OutputDir = "data\backup",
  [string]$MysqlUser = $env:DB_USER,
  [string]$MysqlPassword = $env:DB_PASSWORD,
  [string]$MysqlHost = $env:DB_HOST,
  [string]$MysqlPort = $env:DB_PORT,
  [string]$Database = $env:DB_NAME
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not $MysqlUser) { $MysqlUser = "root" }
if (-not $MysqlPassword) { $MysqlPassword = "1234" }
if (-not $MysqlHost) { $MysqlHost = "127.0.0.1" }
if (-not $MysqlPort) { $MysqlPort = "3306" }
if (-not $Database) { $Database = "yf_vision_rag" }

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$out = Join-Path $root $OutputDir
New-Item -ItemType Directory -Force $out | Out-Null

$sqlFile = Join-Path $out "$Database`_$stamp.sql"
$dataZip = Join-Path $out "data_files_$stamp.zip"

Write-Host "== Backup MySQL =="
mysqldump -h $MysqlHost -P $MysqlPort -u $MysqlUser "-p$MysqlPassword" --default-character-set=utf8mb4 $Database | Out-File -Encoding utf8 $sqlFile

Write-Host "== Backup data files =="
Compress-Archive -Path "data\*" -DestinationPath $dataZip -Force

Write-Host "Backup complete:"
Write-Host "  SQL:  $sqlFile"
Write-Host "  DATA: $dataZip"
