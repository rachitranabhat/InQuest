<#
  PRISM one-time setup on Windows (PowerShell). Run from the project root:
      powershell -ExecutionPolicy Bypass -File scripts\setup-windows.ps1
  Add -BundleForClaude to also download Linux builds of the same packages into vendor\
  (lets the Claude cloud session install and test the exact stack when its own registry access is blocked).
#>
param([switch]$BundleForClaude)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "== Python backend ==" -ForegroundColor Cyan
if (-not (Test-Path ".venv")) { python -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

Write-Host "== React frontend ==" -ForegroundColor Cyan
Push-Location frontend
npm install
Pop-Location

if ($BundleForClaude) {
  Write-Host "== Bundling Linux packages for the Claude session ==" -ForegroundColor Cyan
  New-Item -ItemType Directory -Force vendor\wheels-linux, vendor\npm-linux | Out-Null
  & .\.venv\Scripts\python.exe -m pip download -r backend\requirements.txt -d vendor\wheels-linux `
      --only-binary=:all: --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 `
      --platform manylinux_2_28_x86_64 --python-version 3.13 --implementation cp
  node scripts\pack-linux-natives.mjs
  # one archive each so they can be transferred as single files
  tar -czf vendor\frontend-node_modules.tgz -C frontend node_modules
  Write-Host "Done. Tell Claude: 'vendor bundle ready'." -ForegroundColor Green
}
Write-Host "Setup complete. Start the app with:  .\.venv\Scripts\python.exe scripts\dev.py" -ForegroundColor Green
