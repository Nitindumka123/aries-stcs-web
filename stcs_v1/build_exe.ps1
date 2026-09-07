# build_exe.ps1
# Automates the creation of STCS_V1.exe

Write-Host "--- STCS-V1 Build Started ---" -ForegroundColor Cyan

# 1. Check for PyInstaller
if (!(Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    Write-Host "Error: PyInstaller not found. Installing..." -ForegroundColor Yellow
    pip install pyinstaller
}

# 2. Check for matplotlib (required for astropy build hooks)
if (!(pip list | Select-String "matplotlib")) {
    Write-Host "Error: matplotlib not found. Installing..." -ForegroundColor Yellow
    pip install matplotlib
}

# 3. Clean previous builds
if (Test-Path "./build") { Remove-Item -Path "./build" -Recurse -Force }
if (Test-Path "./dist") { Remove-Item -Path "./dist" -Recurse -Force }

# 4. Run PyInstaller
Write-Host "Running PyInstaller... (This may take a few minutes)" -ForegroundColor Green
pyinstaller --clean stcs_v1.spec

# 5. Post-build: Copy external dependencies
if (Test-Path "./dist/STCS_V1.exe") {
    Write-Host "Build Successful! Preparing distribution..." -ForegroundColor Green
    
    # Copy config and data directories if they exist
    if (Test-Path "./config") {
        Write-Host "Copying config folder..."
        Copy-Item -Path "./config" -Destination "./dist/config" -Recurse
    }
    if (Test-Path "./data") {
        Write-Host "Copying data folder..."
        Copy-Item -Path "./data" -Destination "./dist/data" -Recurse
    }
    if (Test-Path "./.env") {
        Write-Host "Copying .env file..."
        Copy-Item -Path "./.env" -Destination "./dist/.env"
    }

    Write-Host "--- Done! ---" -ForegroundColor Cyan
    Write-Host "You can find your executable in the 'dist' folder."
} else {
    Write-Host "Error: Build failed. Check the logs above." -ForegroundColor Red
}
