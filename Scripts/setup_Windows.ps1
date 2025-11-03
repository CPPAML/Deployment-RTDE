Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "=== Tablet/Robot Dev Environment Setup (Windows) ==="

$envNameInput = Read-Host "Conda env name [tablet-robot]"
$EnvName = if ([string]::IsNullOrWhiteSpace($envNameInput)) { "tablet-robot" } else { $envNameInput }
$Python  = "3.13"

# Resolve repo root (one level up from this script)
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot   = (Resolve-Path (Join-Path $ScriptRoot "..")).Path
$RtdeDir    = Join-Path $RepoRoot "RTDE_Python_Client_Library"
$ReqFile    = Join-Path $RepoRoot "requirements.txt"

Write-Host "==> Repo root: $RepoRoot"
Write-Host "==> Conda env: $EnvName  (Python $Python)"

function Invoke-Conda {
  param([string[]]$Args)
  if ($env:CONDA_EXE) { & $env:CONDA_EXE @Args; return }
  $candidates = @(
    "conda",
    "$env:USERPROFILE\miniconda3\condabin\conda.bat",
    "$env:USERPROFILE\anaconda3\condabin\conda.bat"
  )
  foreach ($c in $candidates) { try { & $c @Args; return } catch { } }
  throw "Conda not found. Install Miniconda/Anaconda and retry."
}

# Init submodules if needed
if (-not (Test-Path $RtdeDir) -and (Test-Path (Join-Path $RepoRoot ".gitmodules"))) {
  Write-Host "==> Initializing git submodules..."
  Push-Location $RepoRoot
  git submodule update --init --recursive
  Pop-Location
}

# Create env if missing (try default channels, then conda-forge)
$envList = Invoke-Conda @("env","list")
if ($envList -notmatch ("^\s*{0}\s" -f [regex]::Escape($EnvName))) {
  Write-Host "==> Creating conda env '$EnvName' (python=$Python) ..."
  try {
    Invoke-Conda @("create","-y","-n",$EnvName,"python=$Python")
  } catch {
    Write-Host "==> Retrying with conda-forge channel..."
    Invoke-Conda @("create","-y","-n",$EnvName,"-c","conda-forge","python=$Python")
  }
} else {
  Write-Host "==> Conda env '$EnvName' already exists."
}

function CondaRun { param([string[]]$Cmd) Invoke-Conda @("run","-n",$EnvName) + $Cmd }

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
Write-Host "🎉 Done!"
Write-Host "Open a new shell and run:  conda activate $EnvName"
Write-Host "WinTab note: ensure Wintab32.dll is active (you may need to disable Windows Ink for this app in Wacom Tablet Properties)."
