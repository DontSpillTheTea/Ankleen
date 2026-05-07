# dev_link.ps1
# Creates a junction link from Anki's addons folder to your local src directory
# This allows you to live-edit your code without repackaging. Just restart Anki!

$ankiAddonsDir = "$env:APPDATA\Anki2\addons21"
$addonName = "ankleen"
$targetDir = "$ankiAddonsDir\$addonName"
$sourceDir = (Resolve-Path ".\src").Path

Write-Host "Setting up development junction link..."

# Check if old community folder 737007040 exists and warn
$oldCommunityDir = "$ankiAddonsDir\737007040"
if (Test-Path $oldCommunityDir) {
    Write-Host "Warning: Found the old community add-on folder (737007040)." -ForegroundColor Yellow
    Write-Host "You should delete it from Anki so it doesn't conflict with your personal version!" -ForegroundColor Yellow
}

# Remove existing folder/link if it exists
if (Test-Path $targetDir) {
    Write-Host "Removing existing $addonName folder in Anki..."
    Remove-Item -Path $targetDir -Recurse -Force
}

# Create a Junction (doesn't require Administrator privileges unlike SymbolicLink)
Write-Host "Linking: $targetDir  --->  $sourceDir"
New-Item -ItemType Junction -Path $targetDir -Target $sourceDir | Out-Null

Write-Host "Done! You can now edit files in your repo's src/ folder and simply restart Anki to see changes." -ForegroundColor Green
