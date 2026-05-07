# build.ps1
# Zips the contents of the src directory into a redistributable .ankiaddon file

$sourceDir = ".\src\*"
$destZip = ".\ankleen.zip"
$destAddon = ".\ankleen.ankiaddon"

Write-Host "Building Ankleen add-on package..."

# Remove old files if they exist
if (Test-Path $destZip) { Remove-Item $destZip -Force }
if (Test-Path $destAddon) { Remove-Item $destAddon -Force }

# Remove python cache
if (Test-Path ".\src\__pycache__") { Remove-Item ".\src\__pycache__" -Recurse -Force }

# Compress the src directory
Compress-Archive -Path $sourceDir -DestinationPath $destZip -Force

# Rename to .ankiaddon
Rename-Item -Path $destZip -NewName "ankleen.ankiaddon" -Force

Write-Host "Build complete: $destAddon" -ForegroundColor Green
