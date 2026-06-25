@echo off
REM ============================================================================
REM  Build an .msix installer bundle for TidyDek from AppxManifest.xml
REM
REM  Prerequisites:
REM    1. Windows SDK 10.0.17763+  (download from
REM       https://developer.microsoft.com/windows/downloads/windows-sdk/)
REM    2. A code-signing certificate (.pfx) from your Microsoft Partner Center
REM       account.
REM    3. Set PFX_PATH and PFX_PASSWORD below to your real cert details.
REM    4. dist\TidyDek.exe must already exist.
REM    5. assets\Logo.png must exist (256x256 minimum).
REM ============================================================================
setlocal enabledelayedexpansion

REM --- CONFIGURE THESE THREE VALUES ------------------------------------------
set PFX_PATH=YourCert.pfx
set PFX_PASSWORD=YourPassword
set PUBLISHER_CN=CN=YourWindowsDeveloperPublisherID
REM ---------------------------------------------------------------------------

set SDK_DIR="C:\Program Files (x86)\Windows Kits\10\bin\10.0.19041.0\x64"
set APPX_DIR=AppxPackage
set SIGNTOOL="%SDK_DIR%\signtool.exe"
set MAKEPRI="%SDK_DIR%\makepri.exe"
set MAKEAPPX="%SDK_DIR%\makeappx.exe"

if not exist "%PFX_PATH%" (
    echo ERROR: Certificate not found at %PFX_PATH%
    echo Set PFX_PATH and PFX_PASSWORD at the top of this script.
    exit /b 1
)

if not exist "dist\TidyDek.exe" (
    echo ERROR: dist\TidyDek.exe not found. Run pyinstaller first.
    exit /b 1
)

if not exist "assets\Logo.png" (
    echo ERROR: assets\Logo.png not found. Place a 256x256 PNG logo there.
    exit /b 1
)

echo.
echo === Step 1: Generate the package resource index (resources.pri) ===
%MAKEPRI% new -pr . -cf AppxMap.xml -mn YourCompany.TidyDek -of resources.pri -o

echo.
echo === Step 2: Build the .msix package ===
mkdir %APPX_DIR% 2>nul

%MAKEAPPX% pack ^
    -p %APPX_DIR%\TidyDek.msix ^
    -d . ^
    -l AppxManifest.xml ^
    -o

if not exist %APPX_DIR%\TidyDek.msix (
    echo   ERROR: makeappx.exe failed.
    exit /b 1
)
echo   Created: %APPX_DIR%\TidyDek.msix

echo.
echo === Step 3: Sign the .msix with your certificate ===
%SIGNTOOL% sign /fd SHA256 /a /f "%PFX_PATH%" /p %PFX_PASSWORD% ^
    /tr http://timestamp.digicert.com /td SHA256 ^
    %APPX_DIR%\TidyDek.msix

echo.
echo === Done ===
echo   Package: %APPX_DIR%\TidyDek.msix
echo.
echo To sideload: double-click the .msix file.
echo For Store submission: upload to Partner Center.
echo.
pause
