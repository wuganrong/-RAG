param(
  [Parameter(Mandatory=$true)][string]$SqlFile,
  [string]$DataZip = "",
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

Write-Host "== Restore MySQL =="
Get-Content $SqlFile | mysql -h $MysqlHost -P $MysqlPort -u $MysqlUser "-p$MysqlPassword" $Database

if ($DataZip -and (Test-Path $DataZip)) {
  Write-Host "== Restore data files =="
  Expand-Archive -Path $DataZip -DestinationPath "data" -Force
}

Write-Host "Restore complete."
