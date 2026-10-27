# Verifie que Invoke-Step (install.ps1) laisse la sortie sur la console, ne l'emet pas dans le flux
# de la fonction, et conserve un code de sortie scalaire exact.
$ErrorActionPreference = 'Stop'
$env:COACH_INSTALLER_LIB = '1'
. (Join-Path $PSScriptRoot '..\..\install.ps1')
$script:DryRunMode = $false
$py = if (Get-Command python -ErrorAction SilentlyContinue) { 'python' } else { 'python3' }
$fail = 0
foreach ($want in 0, 3) {
    $out = @(Invoke-Step $py @('-c', "print('bonjour tout le monde'); import sys; sys.exit($want)"))
    $code = $script:StepCode
    $branch = if ($code -ne 0) { 'echec' } else { 'ok' }
    $expectedBranch = if ($want -ne 0) { 'echec' } else { 'ok' }
    Write-Host "attendu=$want code=$code type=$($code.GetType().Name) emis_dans_le_flux=$($out.Count) branche=$branch"
    if ($code -isnot [int] -or $code -ne $want -or $branch -ne $expectedBranch -or $out.Count -ne 0) { $fail = 1 }
}
if ($fail) { Write-Host 'ECHEC'; exit 1 }
Write-Host 'OK'
