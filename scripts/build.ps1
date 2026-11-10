$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    $icon = Join-Path (Get-Location) 'assets/icon.ico'
    python -m PyInstaller --noconfirm --onefile --windowed --name ConvAll `
        --icon $icon --add-data "$icon;." `
        --collect-all tkinterdnd2 --collect-all pillow_heif --collect-all pypdfium2 `
        --hidden-import PIL._tkinter_finder --exclude-module numpy `
        --specpath build src/convall.py
    if ($LASTEXITCODE -ne 0) { throw 'Executable build failed' }
    Write-Host 'Executable: dist/ConvAll.exe'
} finally {
    Pop-Location
}
