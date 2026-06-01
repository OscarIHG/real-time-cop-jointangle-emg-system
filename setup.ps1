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
    Write-Host "Downloading 'uv' (ultrafast python package manager)..."
    Invoke-WebRequest -Uri "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip" -OutFile "uv.zip"
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
