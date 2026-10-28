# Installe CoachCloclo (Windows). Usage : irm https://raw.githubusercontent.com/romigour/CoachCloclo/master/install.ps1 | iex   ou   .\install.ps1 [-DryRun]
# Variables : COACH_SOURCE (wheel ; par defaut la wheel de la derniere release GitHub), COACH_INSTALL_NO_START=1 (ne lance pas coach start),
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

    if ($env:COACH_SOURCE) {
        $source = $env:COACH_SOURCE
    } elseif ($Dry) {
        $source = '<wheel de la derniere release GitHub>'
    } else {
        # Wheel de la derniere release GitHub (front deja compile).
        $release = Invoke-RestMethod 'https://api.github.com/repos/romigour/CoachCloclo/releases/latest'
        $source = ($release.assets | Where-Object { $_.name -like '*.whl' } | Select-Object -First 1).browser_download_url
        if (-not $source) {
            Write-Host 'Aucune release publiee sur https://github.com/romigour/CoachCloclo/releases.'
            return 1
        }
    }
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
        if ($listed -match '(?m)^coachcloclo') { $installArgs += '--force' }
    }
    $installArgs += $source

    Write-Host 'Installation de CoachCloclo...'
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
