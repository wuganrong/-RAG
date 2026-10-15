param(
    [switch]$SkipDjangoCheck,
    [switch]$SkipPytest
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

$env:DJANGO_ENV = "test"
$env:DB_ENGINE = "sqlite"
$env:CACHE_BACKEND = "locmem"

Write-Host "== Python syntax check =="
& $Python -m py_compile `
    "__000__django\middleware.py" `
    "__001__rag\ops.py" `
    "__001__rag\management\commands\check_tenant_isolation.py" `
    "__002__kb\views.py" `
    "__005__conversation\views.py" `
    "__006__llm\views.py"

Write-Host "== Frontend JavaScript syntax check =="
$html = Get-Content "__011__frontend\index.html" -Raw -Encoding UTF8
$scripts = [regex]::Matches($html, '<script>([\s\S]*?)</script>') | ForEach-Object { $_.Groups[1].Value }
$joined = [string]::Join("`n", $scripts)
$tmpJs = Join-Path ([System.IO.Path]::GetTempPath()) ("yf-rag-frontend-check-" + [System.Guid]::NewGuid().ToString("N") + ".js")
try {
    Set-Content -Path $tmpJs -Value $joined -Encoding UTF8
    node -e "const fs=require('fs'); new Function(fs.readFileSync(process.argv[1], 'utf8')); console.log('frontend js ok')" $tmpJs
    if ($LASTEXITCODE -ne 0) {
        throw "frontend js syntax check failed"
    }
}
finally {
    if (Test-Path $tmpJs) {
        Remove-Item $tmpJs -Force
    }
}

if (-not $SkipDjangoCheck) {
    Write-Host "== Django system check =="
    & $Python manage.py check

    Write-Host "== Migration consistency check =="
    & $Python manage.py makemigrations --check --dry-run
}

if (-not $SkipPytest) {
    Write-Host "== Pytest =="
    & $Python -m pytest tests
}

Write-Host "All checks passed."
