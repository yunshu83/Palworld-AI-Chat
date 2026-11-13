# Build a distributable zip of the bot.
#
# Whitelist copy on purpose: a blacklist would happily ship config.local.json
# (which contains the API key) or the 160MB scrape cache.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File tools\build-release.ps1
#   powershell -ExecutionPolicy Bypass -File tools\build-release.ps1 -SkipPython

param(
    [string]$Version = "",
    [switch]$SkipPython
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $Root "run.py"))) {
    Write-Host "run.py not found next to tools\. Run this from the project folder." -ForegroundColor Red
    exit 1
}

if (-not $Version) {
    $Version = Get-Date -Format "yyyyMMdd"
}

$DistRoot = Join-Path $Root "dist"
$Name = "palworld-deepseek-bot-$Version"
$Stage = Join-Path $DistRoot $Name
$Zip = Join-Path $DistRoot "$Name.zip"

if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path $Stage | Out-Null

# --- files ---
$files = @(
    "run.py",
    "start.bat",
    "setup.bat",
    "config.example.toml",
    "README.md",
    "LICENSE",
    "persona.md",
    "persona-lite.md",
    "server_facts.md",
    ".gitignore"
)
foreach ($item in $files) {
    $source = Join-Path $Root $item
    if (Test-Path $source) {
        Copy-Item $source (Join-Path $Stage $item) -Force
    }
}

# --- folders: whole tree without junk ---
function Copy-Tree([string]$from, [string]$to, [string[]]$excludeDirs, [string[]]$excludeFiles) {
    if (-not (Test-Path $from)) { return }
    New-Item -ItemType Directory -Force -Path $to | Out-Null
    Get-ChildItem $from -Force | ForEach-Object {
        $name = $_.Name
        if ($_.PSIsContainer) {
            if ($excludeDirs -contains $name) { return }
            Copy-Tree $_.FullName (Join-Path $to $name) $excludeDirs $excludeFiles
        } else {
            if ($excludeFiles -contains $name) { return }
            Copy-Item $_.FullName (Join-Path $to $name) -Force
        }
    }
}

$excludeDirs = @("__pycache__", "raw", "raw_extra", "backup", "logs")
$excludeFiles = @(
    "config.toml",
    "config.local.json",
    ".palbot.lock",
    "memory.json"
)

Copy-Tree (Join-Path $Root "bot") (Join-Path $Stage "bot") $excludeDirs $excludeFiles
Copy-Tree (Join-Path $Root "data") (Join-Path $Stage "data") $excludeDirs $excludeFiles
Copy-Tree (Join-Path $Root "tools") (Join-Path $Stage "tools") $excludeDirs $excludeFiles
Copy-Tree (Join-Path $Root "ue4ss") (Join-Path $Stage "ue4ss") $excludeDirs $excludeFiles
Copy-Tree (Join-Path $Root "docs") (Join-Path $Stage "docs") $excludeDirs $excludeFiles
Copy-Tree (Join-Path $Root "tests") (Join-Path $Stage "tests") $excludeDirs $excludeFiles

# --- embedded python (optional but this is what makes it "no install needed") ---
if (-not $SkipPython) {
    $python = Join-Path $Root "python"
    if (Test-Path (Join-Path $python "python.exe")) {
        Copy-Tree $python (Join-Path $Stage "python") @("__pycache__") @()
    } else {
        Write-Host "WARN: python\ not found, release will require system Python 3.11+" -ForegroundColor Yellow
    }
}

# --- sanity: never ship secrets ---
$leaks = Get-ChildItem $Stage -Recurse -File | Where-Object { $_.Name -in @("config.local.json", "config.toml") }
if ($leaks) {
    Write-Host "ABORT: config files leaked into staging:" -ForegroundColor Red
    $leaks | ForEach-Object { Write-Host "  $($_.FullName)" }
    exit 1
}

if (Test-Path $Zip) { Remove-Item $Zip -Force }
Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $Zip -CompressionLevel Optimal

$size = [math]::Round((Get-Item $Zip).Length / 1MB, 1)
Write-Host ""
Write-Host "OK  $Zip  ($size MB)" -ForegroundColor Green
Write-Host "Stage: $Stage"
