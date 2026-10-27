# Installe Coach (Windows). Usage : .\install.ps1 [-DryRun]
# Variables : COACH_SOURCE (wheel ou nom de paquet), COACH_INSTALL_NO_START=1 (ne lance pas coach start),
# COACH_INSTALL_OFFLINE=1 (doctor sans Claude ni Garmin, pour la CI).
param([switch]$DryRun)
$ErrorActionPreference = 'Stop'

function Invoke-Step {
    param([string]$Exe, [string[]]$StepArgs)
    if ($DryRun) { Write-Host "[dry-run] $Exe $($StepArgs -join ' ')"; return 0 }
    & $Exe @StepArgs | Out-Host
    return $LASTEXITCODE
}

function Update-SessionPath {
    $localBin = Join-Path $HOME '.local\bin'
    if (($env:Path -split ';') -notcontains $localBin) { $env:Path = "$localBin;$env:Path" }
}

$source = if ($env:COACH_SOURCE) { $env:COACH_SOURCE } else { 'coach-running' }
Update-SessionPath

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host 'Installation de uv...'
    if ($DryRun) {
        Write-Host '[dry-run] irm https://astral.sh/uv/install.ps1 | iex'
    } else {
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    }
    Update-SessionPath
}

$installArgs = @('tool', 'install', '--python', '3.12')
if (-not $DryRun -and (Get-Command uv -ErrorAction SilentlyContinue)) {
    $listed = (& uv tool list 2>$null) -join "`n"
    if ($listed -match '(?m)^coach-running') { $installArgs += '--force' }
}
$installArgs += $source

Write-Host 'Installation de Coach...'
$code = Invoke-Step 'uv' $installArgs
if ($code -ne 0) { Write-Error "uv tool install a echoue (code $code)"; exit 1 }

Write-Host "Verification de l'installation..."
$doctorArgs = @('doctor', '--fix')
if ($env:COACH_INSTALL_OFFLINE -eq '1') { $doctorArgs += '--offline' }
$code = Invoke-Step 'coach' $doctorArgs
if ($code -ne 0) {
    Write-Host 'Certaines verifications ont echoue (lignes x ci-dessus). Corrige-les puis relance ce script.'
    exit 1
}

if ($env:COACH_INSTALL_NO_START -eq '1') {
    Write-Host 'Installation terminee (COACH_INSTALL_NO_START=1 : coach start non lance).'
    exit 0
}
Invoke-Step 'coach' @('start') | Out-Null
