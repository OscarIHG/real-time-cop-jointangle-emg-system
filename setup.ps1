<#
.SYNOPSIS
Setup script for Real-Time CoP-JointAngle-EMG System on Windows.
Uses 'uv' to automatically provision Python 3.11 for MediaPipe compatibility.
#>

Write-Host "========================================================"
Write-Host "STARTING REAL-TIME COP-JOINTANGLE-EMG SYSTEM SETUP (WINDOWS)"
Write-Host "========================================================"

# 1. Download uv if not present
$uv_exe = ".\uv_bin\uv.exe"
if (-not (Test-Path $uv_exe)) {
    $uv_version = if ($env:UV_VERSION) { $env:UV_VERSION } else { "0.8.14" }
    $uv_sha256 = $env:UV_SHA256
    if ([string]::IsNullOrWhiteSpace($uv_sha256)) {
        throw "Set UV_SHA256 to the vendor-published SHA-256 for uv v$uv_version before running setup."
    }
    $uv_url = "https://github.com/astral-sh/uv/releases/download/$uv_version/uv-x86_64-pc-windows-msvc.zip"
    Write-Host "Downloading verified uv $uv_version..."
    Invoke-WebRequest -Uri $uv_url -OutFile "uv.zip"
    $actual_hash = (Get-FileHash -Algorithm SHA256 -LiteralPath "uv.zip").Hash
    if ($actual_hash -ne $uv_sha256.ToUpperInvariant()) {
        Remove-Item -LiteralPath "uv.zip" -Force
        throw "uv.zip SHA-256 mismatch."
    }
    Expand-Archive -Path "uv.zip" -DestinationPath "uv_bin" -Force
    Remove-Item "uv.zip"
}

# 2. Create Venv with Python 3.11
$venv_dir = "venv"
Write-Host "Creating Python 3.11 virtual environment in .\$venv_dir (this ensures MediaPipe compatibility)..."
# Using --python 3.11 forces uv to download an isolated Python 3.11 binary for Windows if needed!
& $uv_exe venv --python 3.11 $venv_dir --clear

if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Failed to create virtual environment." -ForegroundColor Red
    exit 1
}

# 3. Install dependencies using uv pip
Write-Host "Installing dependencies from requirements.txt (blazing fast)..."
& $uv_exe pip install -r requirements.txt --python ".\$venv_dir"

if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Failed to install dependencies." -ForegroundColor Red
    exit 1
}

Write-Host "========================================================" -ForegroundColor Green
Write-Host "[SUCCESS] Windows Setup Complete!" -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Green
Write-Host ""
Write-Host "To start the application, run the following command:"
Write-Host ".\venv\Scripts\python.exe -m acquisition_systems.app_gui" -ForegroundColor Cyan
Write-Host ""
Write-Host "IMPORTANT: Remember to pair your ESP32 in Windows Settings and update 'emg_com_port' in config.yaml!" -ForegroundColor Yellow
