param(
  [Parameter(Mandatory = $true)]
  [string]$BackupPath
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$backupRoot = (Resolve-Path -LiteralPath $BackupPath).Path
$openpilotRoot = Join-Path $backupRoot "openpilot"
if (-not (Test-Path -LiteralPath $openpilotRoot)) {
  throw "The backup does not contain an openpilot folder: $openpilotRoot"
}

$deviceControllers = Get-ChildItem -LiteralPath $openpilotRoot -Recurse -Filter "carcontroller.py" |
  Where-Object { $_.FullName -match "volkswagen" }
if (-not $deviceControllers) {
  throw "No Volkswagen carcontroller.py was found in the backup."
}

$references = @{
  "deprecated-release2" = Join-Path $projectRoot "vendor/dragonpilot-release2/selfdrive/car/volkswagen/carcontroller.py"
  "d2" = Join-Path $projectRoot "vendor/dragonpilot-d2/selfdrive/car/volkswagen/carcontroller.py"
  "deprecated-beta2-c6" = Join-Path $projectRoot "vendor/dragonpilot-beta2-c6/selfdrive/car/volkswagen/carcontroller.py"
}

$diffRoot = Join-Path $backupRoot "reference-diffs"
New-Item -ItemType Directory -Force -Path $diffRoot | Out-Null

foreach ($deviceController in $deviceControllers) {
  $deviceLabel = ($deviceController.FullName.Substring($openpilotRoot.Length).TrimStart('\') -replace '[\\/:*?"<>|]', '_')
  foreach ($referenceName in $references.Keys) {
    $reference = $references[$referenceName]
    if (-not (Test-Path -LiteralPath $reference)) {
      Write-Warning "Reference missing: $reference"
      continue
    }
    $outputPath = Join-Path $diffRoot ("$deviceLabel-vs-$referenceName.diff")
    & git diff --no-index --no-color -- $reference $deviceController.FullName 2>&1 |
      Set-Content -LiteralPath $outputPath -Encoding utf8
    if ($LASTEXITCODE -notin 0, 1) {
      throw "git diff failed for $referenceName"
    }
  }
}

Write-Host "Reference comparisons written to: $diffRoot"
