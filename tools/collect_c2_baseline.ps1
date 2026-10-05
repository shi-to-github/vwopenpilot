param(
  [Parameter(Mandatory = $true)]
  [string]$C2Ip,
  [int]$Port = 8022,
  [string]$User = "root",
  [string]$Destination = (Join-Path (Get-Location) ("c2-baseline-" + (Get-Date -Format "yyyyMMdd-HHmmss"))),
  [string]$IdentityFile = (Join-Path $env:USERPROFILE ".ssh\vwopenploot_c2_id_rsa"),
  [string]$KnownHostsFile = (Join-Path $env:USERPROFILE ".ssh\known_hosts_vwopenploot_c2")
)

$ErrorActionPreference = "Stop"
$collector = Join-Path $PSScriptRoot "collect_c2_baseline.py"
& python $collector --ip $C2Ip --port $Port --user $User --identity $IdentityFile --known-hosts $KnownHostsFile --destination $Destination
if ($LASTEXITCODE -ne 0) { throw "C2 baseline collection or verification failed." }
