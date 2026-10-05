$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
  python -m unittest discover -s tests -v
  if ($LASTEXITCODE -ne 0) { throw "Offline tests failed." }
} finally {
  Pop-Location
}

