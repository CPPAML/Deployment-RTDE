Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "=== Tablet/Robot Dev Environment Setup (Windows) ==="

$envNameInput = Read-Host "Conda env name [tablet-robot]"
$EnvName = if ([string]::IsNullOrWhiteSpace($envNameInput)) { "tablet-robot" } else { $envNameInput }
$Python  = "3.13"

# ----- helpers first (safer) -----
function Invoke-Conda {
  param([string[]]$CondaArgs)

  if ($env:CONDA_EXE) { & $env:CONDA_EXE @CondaArgs; return }

  $candidates = @(
    "$env:USERPROFILE\miniconda3\condabin\conda.bat",
    "$env:USERPROFILE\miniconda3\Scripts\conda.exe",
    "$env:USERPROFILE\anaconda3\condabin\conda.bat",
    "$env:USERPROFILE\anaconda3\Scripts\conda.exe",
    "conda"
  )
  foreach ($c in $candidates) {
    try { & $c @CondaArgs; return } catch { }
  }
  throw "Conda not found. Install Miniconda/Anaconda and retry."
}

function CondaRun {
  param([string[]]$Cmd)
  $allArgs = @("run","-n",$EnvName) + $Cmd
  Invoke-Conda $allArgs
}

# ----- repo paths -----
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot   = (Resolve-Path (Join-Path $ScriptRoot "..")).Path
$RtdeDir    = Join-Path $RepoRoot "RTDE_Python_Client_Library"
$ReqFile    = Join-Path $RepoRoot "requirements.txt"

Write-Host "==> Repo root: $RepoRoot"
Write-Host "==> Conda env: $EnvName  (Python $Python)"

# Init submodules if needed
if (-not (Test-Path $RtdeDir) -and (Test-Path (Join-Path $RepoRoot ".gitmodules"))) {
  Write-Host "==> Initializing git submodules..."
  Push-Location $RepoRoot
  git submodule update --init --recursive
  Pop-Location
}

# ----- create env if missing -----
$envListText = (Invoke-Conda @("env","list") | Out-String)
$pattern = "(?m)^\s*{0}\s" -f [regex]::Escape($EnvName)

if ($envListText -match $pattern) {
  Write-Host "==> Conda env '$EnvName' already exists."
} else {
  Write-Host "==> Creating conda env '$EnvName' (python=$Python) ..."
  $created = $false
  try {
    Invoke-Conda @("create","-y","-n",$EnvName,"python=$Python")
    $created = $true
  } catch {
    Write-Host "==> Retrying with conda-forge channel..."
    try {
      Invoke-Conda @("create","-y","-n",$EnvName,"-c","conda-forge","python=$Python")
      $created = $true
    } catch {
      Write-Warning "Python $Python not available; falling back to 3.12 on conda-forge..."
      Invoke-Conda @("create","-y","-n",$EnvName,"-c","conda-forge","python=3.12")
      $created = $true
    }
  }

  # verify creation actually worked
  $envListText = (Invoke-Conda @("env","list") | Out-String)
  if ($envListText -notmatch $pattern) {
    throw "Conda environment '$EnvName' was not created successfully."
  }
}

# ----- package installs -----
Write-Host "==> Upgrading pip..."
CondaRun @("python","-m","pip","install","--upgrade","pip")

if (Test-Path $ReqFile) {
  Write-Host "==> Installing from requirements.txt..."
  CondaRun @("pip","install","-r",$ReqFile)
} else {
  Write-Warning "requirements.txt not found at $ReqFile (skipping)."
}

if (Test-Path $RtdeDir) {
  Write-Host "==> pip install -e $RtdeDir"
  CondaRun @("pip","install","-e",$RtdeDir)
} else {
  Write-Warning "RTDE_Python_Client_Library not found at $RtdeDir; skipping editable install."
}

Write-Host ""
Write-Host "Done!"
Write-Host "Open a new shell and run:  conda activate $EnvName"
Write-Host "WinTab note: ensure Wintab32.dll is active (you may need to disable Windows Ink for this app in Wacom Tablet Properties)."
