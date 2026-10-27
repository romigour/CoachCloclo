# Installe Coach (Windows). Usage : irm <URL>/install.ps1 | iex   ou   .\install.ps1 [-DryRun]
# Variables : COACH_SOURCE (wheel ou nom de paquet), COACH_INSTALL_NO_START=1 (ne lance pas coach start),
# COACH_INSTALL_OFFLINE=1 (doctor sans Claude ni Garmin, pour la CI).
# Sous `irm | iex`, DryRun n'est pas disponible : definir $env:COACH_DRY_RUN = '1'.
param([switch]$DryRun)

# Tout est dans une fonction : `exit` fermerait la fenetre de l'utilisateur sous `irm | iex`.
function Install-Coach {
    param([bool]$Dry)
    $ErrorActionPreference = 'Stop'
    $env:PYTHONUTF8 = '1'

    function Update-SessionPath {
        $localBin = Join-Path $HOME '.local\bin'
        if (($env:Path -split ';') -notcontains $localBin) { $env:Path = "$localBin;$env:Path" }
    }

    # Lance une commande native (non redirigee : reste interactive) ; renvoie son code de sortie.
    function Invoke-Step {
        param([string]$Exe, [string[]]$StepArgs)
        if ($Dry) { Write-Host "[dry-run] $Exe $($StepArgs -join ' ')"; return 0 }
        & $Exe @StepArgs
        return $LASTEXITCODE
    }

    $source = if ($env:COACH_SOURCE) { $env:COACH_SOURCE } else { 'coach-running' }
    Update-SessionPath

    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Host 'Installation de uv...'
        if ($Dry) {
            Write-Host '[dry-run] irm https://astral.sh/uv/install.ps1 | iex'
        } else {
            Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
        }
        Update-SessionPath
    }

    $installArgs = @('tool', 'install', '--python', '3.12')
    if (-not $Dry -and (Get-Command uv -ErrorAction SilentlyContinue)) {
        $listed = ''
        try {
            $ErrorActionPreference = 'Continue'
            $listed = (& uv tool list 2>$null) -join "`n"
        } catch { $listed = '' }
        $ErrorActionPreference = 'Stop'
        if ($listed -match '(?m)^coach-running') { $installArgs += '--force' }
    }
    $installArgs += $source

    Write-Host 'Installation de Coach...'
    $code = Invoke-Step 'uv' $installArgs
    if ($code -ne 0) { Write-Host "uv tool install a echoue (code $code)."; return 1 }

    Write-Host "Verification de l'installation..."
    $doctorArgs = @('doctor', '--fix')
    if ($env:COACH_INSTALL_OFFLINE -eq '1') { $doctorArgs += '--offline' }
    $code = Invoke-Step 'coach' $doctorArgs
    if ($code -ne 0) {
        Write-Host 'Certaines verifications ont echoue (lignes x ci-dessus). Corrige-les puis relance ce script.'
        return 1
    }

    if ($env:COACH_INSTALL_NO_START -eq '1') {
        Write-Host 'Installation terminee (COACH_INSTALL_NO_START=1 : coach start non lance).'
        return 0
    }
    return (Invoke-Step 'coach' @('start'))
}

$dry = $DryRun.IsPresent -or ($env:COACH_DRY_RUN -eq '1')
try {
    $result = Install-Coach -Dry $dry
} catch {
    Write-Host "Erreur : $($_.Exception.Message)"
    $result = 1
}
# Lance comme fichier : code de sortie. Sous `irm | iex` : pas d'exit (ferme la fenetre).
if ($PSCommandPath -and $result -ne 0) { exit $result }
