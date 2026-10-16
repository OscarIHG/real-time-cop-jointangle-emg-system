<#
.SYNOPSIS
Automated setup for the Real-Time CoP-JointAngle-EMG System on Windows 10/11.

.DESCRIPTION
  .\setup.ps1            install or update (safe to run again)
  .\setup.ps1 -Clean     delete the Python environment and rebuild it
  .\setup.ps1 -SkipDriver  do not install the Phidget22 driver

What it does:
  1. Downloads a pinned release of 'uv' (verified SHA-256) into .\uv_bin
  2. Installs the Phidget22 driver for the PhidgetBridge 1046_1 (verified SHA-256)
  3. Creates a self-contained Python 3.11 environment in .\venv
  4. Installs requirements.txt
  5. Runs the diagnostic: python -m acquisition_systems.doctor

If PowerShell blocks the script, run it once with:
  powershell -ExecutionPolicy Bypass -File .\setup.ps1
#>
param(
    [switch]$Clean,
    [switch]$SkipDriver
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # Invoke-WebRequest is much faster without the progress bar
Set-Location -LiteralPath $PSScriptRoot

# --- Pinned downloads (update together with their checksums) ------------------
$UvVersion = "0.13.1"
$UvSha256 = @{
    "x86_64"  = "3b2661a463a5baea7f5076ea2b25ab71d77f36a6c0d809e5350651792f80a672"
    "aarch64" = "ec7846a5939b4654afee24f2d82bf6fde71bd7a6952d7748f1135ab301dd0a49"
}
$PhidgetsVersion = "1.26.20260821"
$PhidgetsUrl = "https://www.phidgets.com/downloads/phidget22/libraries/windows/Phidget22-x64/Phidget22-x64_$PhidgetsVersion.exe"
$PhidgetsSha256 = "e41b90148b608139f703ca4f0267395566c0ab346cef2ac7ad9fa933538f6c0d"
$PythonVersion = "3.11"

function Step($text)  { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Ok($text)    { Write-Host "    $text" -ForegroundColor Green }
function Warn($text)  { Write-Host "    $text" -ForegroundColor Yellow }
function Fail($text)  { Write-Host "ERROR: $text" -ForegroundColor Red; exit 1 }

function Get-VerifiedFile($Url, $Destination, $Sha256) {
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing
            break
        } catch {
            if ($attempt -eq 3) { Fail "download failed: $Url ($($_.Exception.Message))" }
            Start-Sleep -Seconds 3
        }
    }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Destination).Hash
    if ($actual -ne $Sha256.ToUpperInvariant()) {
        Remove-Item -LiteralPath $Destination -Force
        Fail "checksum mismatch for $Url (download corrupted or tampered)"
    }
}

Write-Host "REAL-TIME COP-JOINTANGLE-EMG SYSTEM SETUP (WINDOWS)" -ForegroundColor Cyan
Write-Host "    Folder: $PSScriptRoot"

$Arch = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "aarch64" } else { "x86_64" }
if (-not [Environment]::Is64BitOperatingSystem) { Fail "a 64-bit Windows is required." }

# --- 1. uv (Python and package manager) --------------------------------------
Step "1/5 uv $UvVersion"
$UvExe = Join-Path $PSScriptRoot "uv_bin\uv.exe"
$UvCurrent = if (Test-Path $UvExe) { (& $UvExe --version) 2>$null } else { "" }
if ($UvCurrent -notlike "uv $UvVersion*") {
    $Zip = Join-Path $env:TEMP "uv-$UvVersion.zip"
    Get-VerifiedFile "https://github.com/astral-sh/uv/releases/download/$UvVersion/uv-$Arch-pc-windows-msvc.zip" $Zip $UvSha256[$Arch]
    if (Test-Path "uv_bin") { Remove-Item -Recurse -Force "uv_bin" }
    Expand-Archive -Path $Zip -DestinationPath "uv_bin" -Force
    Remove-Item -LiteralPath $Zip -Force
    Ok "uv $UvVersion verified and installed in .\uv_bin"
} else {
    Ok "$UvCurrent already installed"
}

# --- 2. Phidget22 driver ------------------------------------------------------
Step "2/5 Phidget22 driver (PhidgetBridge 1046_1)"
$PhidgetDll = Join-Path $env:SystemRoot "System32\phidget22.dll"
if ($SkipDriver) {
    Warn "skipped (-SkipDriver)"
} elseif (Test-Path $PhidgetDll) {
    Ok "already installed ($PhidgetDll)"
} elseif ($Arch -ne "x86_64") {
    Warn "no automatic installer for ARM64; install it from https://www.phidgets.com/docs/OS_-_Windows"
} else {
    $Installer = Join-Path $env:TEMP "Phidget22-x64_$PhidgetsVersion.exe"
    Get-VerifiedFile $PhidgetsUrl $Installer $PhidgetsSha256
    Write-Host "    Opening the Phidget22 installer: accept the administrator prompt and click through it."
    try {
        # Interactive on purpose: the vendor does not document silent-install switches.
        $proc = Start-Process -FilePath $Installer -Verb RunAs -Wait -PassThru
        if ($proc.ExitCode -ne 0) { Warn "installer exit code $($proc.ExitCode)" }
    } catch {
        Warn "the driver installer was cancelled; run it later: $Installer"
    }
    if (Test-Path $PhidgetDll) { Ok "Phidget22 driver installed" }
    else { Warn "driver not detected; the force plate will be offline until it is installed" }
}

# --- 3. Python environment ----------------------------------------------------
Step "3/5 Python $PythonVersion environment (.\venv)"
$VenvPython = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
if ($Clean -and (Test-Path "venv")) {
    Warn "-Clean: removing the existing .\venv"
    Remove-Item -Recurse -Force "venv"
}
$NeedVenv = $true
if (Test-Path $VenvPython) {
    $ver = (& $VenvPython -c "import sys; print('%d.%d' % sys.version_info[:2])") 2>$null
    if ($ver -eq $PythonVersion) { $NeedVenv = $false }
}
if ($NeedVenv) {
    # uv downloads an isolated Python 3.11 if none is installed; the system Python is untouched.
    & $UvExe venv --python $PythonVersion venv --clear
    if ($LASTEXITCODE -ne 0) { Fail "could not create the virtual environment" }
    Ok "environment created"
} else {
    Ok "environment already exists (use -Clean to rebuild)"
}

# --- 4. Python packages -------------------------------------------------------
Step "4/5 Python dependencies"
& $UvExe pip install -r requirements.txt --python $VenvPython
if ($LASTEXITCODE -ne 0) { Fail "dependency installation failed" }
Ok "requirements.txt installed"

# --- 5. Diagnostic ------------------------------------------------------------
Step "5/5 Diagnostic"
& $VenvPython -m acquisition_systems.doctor
$DoctorStatus = $LASTEXITCODE

Write-Host ""
if ($DoctorStatus -eq 0) {
    Write-Host "SETUP COMPLETED" -ForegroundColor Green
} else {
    Write-Host "SETUP COMPLETED, but the diagnostic reported errors (see above)." -ForegroundColor Yellow
}
Write-Host "    Run the application:  .\venv\Scripts\python.exe -m acquisition_systems.app_gui"
Write-Host "    Re-check hardware:    .\venv\Scripts\python.exe -m acquisition_systems.doctor"
Write-Host "    ESP32: pair it in Windows Bluetooth settings and set emg_com_port in config.yaml" -ForegroundColor Yellow
exit $DoctorStatus
