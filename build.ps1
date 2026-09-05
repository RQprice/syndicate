param(
    [switch]$SkipZip
)

$ErrorActionPreference = "Stop"
$appName = "SYNDICATE"

if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    Write-Host "PyInstaller is not installed. Install it with:"
    Write-Host "  py -m pip install pyinstaller"
    exit 1
}

$tesseractDir = Join-Path $PSScriptRoot "vendor\Tesseract-OCR"
if (-not (Test-Path (Join-Path $tesseractDir "tesseract.exe"))) {
    Write-Host "Bundled OCR engine not found: $tesseractDir"
    exit 1
}

$rapidModelsDir = Join-Path $PSScriptRoot "vendor\RapidOCR-models"
if (-not (Test-Path (Join-Path $rapidModelsDir "ch_PP-OCRv5_rec_mobile.onnx"))) {
    Write-Host "Bundled neural OCR models not found: $rapidModelsDir"
    exit 1
}

$guildIconPng = Join-Path $PSScriptRoot "imgs\guild icon.png"
$appIconPng = Join-Path $PSScriptRoot "imgs\guild app icon.png"
$appIconIco = Join-Path $PSScriptRoot "imgs\guild app icon.ico"
$dataFile = Join-Path $PSScriptRoot "data.json"
if (-not (Test-Path $guildIconPng)) {
    Write-Host "Guild icon not found: $guildIconPng"
    exit 1
}
if (-not (Test-Path $appIconPng)) {
    Write-Host "Application icon not found: $appIconPng"
    exit 1
}
if (-not (Test-Path $appIconIco)) {
    Write-Host "Windows application icon not found: $appIconIco"
    exit 1
}
if (-not (Test-Path $dataFile)) {
    Write-Host "Application data not found: $dataFile"
    exit 1
}

pyinstaller --noconfirm --clean --onefile --windowed `
    --add-data "$tesseractDir;tesseract" `
    --add-data "$rapidModelsDir;rapidocr_models" `
    --add-data "$guildIconPng;imgs" `
    --add-data "$appIconPng;imgs" `
    --add-data "$appIconIco;imgs" `
    --icon "$appIconIco" `
    --collect-data rapidocr `
    --name $appName app.py
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}
$distDataFile = Join-Path $PSScriptRoot "dist\data.json"
if (-not (Test-Path $distDataFile)) {
    Copy-Item -LiteralPath $dataFile -Destination $distDataFile
    Write-Host "Copied initial data: dist\data.json"
} else {
    Write-Host "Preserved existing user data: dist\data.json"
}
$distExe = Join-Path $PSScriptRoot "dist\$appName.exe"
if (-not $SkipZip) {
    $archive = Join-Path $PSScriptRoot "dist\$appName.zip"
    Compress-Archive `
        -LiteralPath $distExe, $distDataFile `
        -DestinationPath $archive `
        -CompressionLevel Optimal `
        -Force
    Write-Host "Created portable archive: dist\$appName.zip"
} else {
    Write-Host "Skipped portable archive"
}
Write-Host "Done: dist\$appName.exe"
