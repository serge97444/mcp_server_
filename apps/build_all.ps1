$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")

$minimalSrc = Join-Path $repoRoot "apps/minimal-ui/formulaire.html"
$minimalDest = Join-Path $repoRoot "custom_version/Assets/minimal/formulaire.html"

Write-Host "Copying minimal UI..."
Copy-Item -Path $minimalSrc -Destination $minimalDest -Force

Write-Host "Building rich UI (React)..."
Push-Location (Join-Path $repoRoot "apps/rich-ui")
npm install
npm run build
Pop-Location

Write-Host "Done."
