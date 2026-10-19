# Start Local Development Server for DataScrapper (Bare-Metal / No Docker)
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-Path "$scriptDir\..\..\"
Set-Location $projectRoot

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Starting DataScrapper Server on http://localhost:8085    " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# Set environment variables
$env:PORT = "8085"
$env:PYTHONPATH = "$projectRoot"

py "apps\api\src\server.py"
