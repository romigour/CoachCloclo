# Installe Coach (Windows). Usage : irm <URL>/install.ps1 | iex   ou   .\install.ps1 [-DryRun]
# Variables : COACH_SOURCE (wheel ou nom de paquet), COACH_INSTALL_NO_START=1 (ne lance pas coach start),
# COACH_INSTALL_OFFLINE=1 (doctor sans Claude ni Garmin, pour la CI).
# Sous `irm | iex`, DryRun n'est pas disponible : definir $env:COACH_DRY_RUN = '1'.
param([switch]$DryRun)

# Tout est dans une fonction : `exit` fermerait la fenetre de l'utilisateur sous `irm | iex`.
# Lance une commande native sans rien capturer (sortie et terminal restent attaches a la console).
# Le code de sortie est laisse dans $script:StepCode, jamais dans le flux de sortie de la fonction.
function Invoke-Step {
    param([string]$Exe, [string[]]$StepArgs)
    $script:StepCode = 0
    if ($script:DryRunMode) { Write-Host "[dry-run] $Exe $($StepArgs -join ' ')"; return }
    # Start-Process : le fils herite directement de la console (aucune capture, interactivite conservee).
    $path = (Get-Command $Exe -CommandType Application | Select-Object -First 1).Source
    $quoted = $StepArgs | ForEach-Object { if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ } }
    $proc = Start-Process -FilePath $path -ArgumentList $quoted -NoNewWindow -Wait -PassThru
    $script:StepCode = [int]$proc.ExitCode
}

function Install-Coach {
    param([bool]$Dry)
    $script:DryRunMode = $Dry
    $ErrorActionPreference = 'Stop'
    $env:PYTHONUTF8 = '1'

    function Update-SessionPath {
        $localBin = Join-Path $HOME '.local\bin'
        if (($env:Path -split ';') -notcontains $localBin) { $env:Path = "$localBin;$env:Path" }
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
    Invoke-Step 'uv' $installArgs
    $code = $script:StepCode
    if ($code -ne 0) { Write-Host "uv tool install a echoue (code $code)."; return 1 }

    Write-Host "Verification de l'installation..."
    $doctorArgs = @('doctor', '--fix')
    if ($env:COACH_INSTALL_OFFLINE -eq '1') { $doctorArgs += '--offline' }
    Invoke-Step 'coach' $doctorArgs
    $code = $script:StepCode
    if ($code -ne 0) {
        Write-Host 'Certaines verifications ont echoue (lignes x ci-dessus). Corrige-les puis relance ce script.'
        return 1
    }

    if ($env:COACH_INSTALL_NO_START -eq '1') {
        Write-Host 'Installation terminee (COACH_INSTALL_NO_START=1 : coach start non lance).'
        return 0
    }
    Invoke-Step 'coach' @('start')
    return $script:StepCode
}

if ($env:COACH_INSTALLER_LIB -eq '1') { return }  # chargement des fonctions seules (tests)
$dry = $DryRun.IsPresent -or ($env:COACH_DRY_RUN -eq '1')
try {
    $result = Install-Coach -Dry $dry
} catch {
    Write-Host "Erreur : $($_.Exception.Message)"
    $result = 1
}
# Lance comme fichier : code de sortie. Sous `irm | iex` : pas d'exit (ferme la fenetre).
if ($PSCommandPath -and $result -ne 0) { exit $result }
