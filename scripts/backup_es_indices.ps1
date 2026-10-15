param(
  [string]$EsUrl = $env:ES_HOSTS,
  [string]$OutputDir = "data\backup\es",
  [string]$IndexPattern = "kb_*"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not $EsUrl) { $EsUrl = "http://127.0.0.1:9200" }
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$out = Join-Path $root $OutputDir
New-Item -ItemType Directory -Force $out | Out-Null

$indices = Invoke-RestMethod -Method Get -Uri "$EsUrl/_cat/indices/$IndexPattern?h=index&format=json"
foreach ($item in $indices) {
  $index = $item.index
  if (-not $index) { continue }
  $file = Join-Path $out "$index`_$stamp.json"
  Write-Host "Backing up ES index $index -> $file"
  $body = @{ query = @{ match_all = @{} }; size = 10000 } | ConvertTo-Json -Depth 10
  $result = Invoke-RestMethod -Method Post -Uri "$EsUrl/$index/_search" -ContentType "application/json" -Body $body
  $result.hits.hits | ConvertTo-Json -Depth 20 | Out-File -Encoding utf8 $file
}

Write-Host "ES backup complete: $out"
