param(
  [string]$EsUrl = $env:ES_HOSTS,
  [Parameter(Mandatory=$true)][string]$InputFile,
  [Parameter(Mandatory=$true)][string]$Index
)

$ErrorActionPreference = "Stop"
if (-not $EsUrl) { $EsUrl = "http://127.0.0.1:9200" }

$docs = Get-Content $InputFile -Raw | ConvertFrom-Json
$bulkLines = New-Object System.Collections.Generic.List[string]
foreach ($doc in $docs) {
  $id = $doc._id
  $bulkLines.Add((@{ index = @{ _index = $Index; _id = $id } } | ConvertTo-Json -Compress))
  $bulkLines.Add(($doc._source | ConvertTo-Json -Depth 20 -Compress))
}
$bulkBody = ($bulkLines -join "`n") + "`n"
Invoke-RestMethod -Method Post -Uri "$EsUrl/_bulk" -ContentType "application/x-ndjson" -Body $bulkBody | Out-Null
Write-Host "ES restore complete: $InputFile -> $Index"
