# Start Palworld dedicated server (hidden) and the chat bot, then keep the bot
# running only while the server runs.
#
# ASCII only on purpose: Windows PowerShell 5.1 misparses UTF-8 .ps1 files
# without a BOM, and a half-broken script is worse than no script.
#
# Paths are derived, not hardcoded:
#   - bot dir  = parent of this script's folder
#   - python   = <bot>\python\python.exe if present, else python on PATH
#   - server   = from config.local.json / config.toml log_path, or -ServerRoot

param(
    [string]$ServerRoot = ""
)

$ErrorActionPreference = "Continue"

$BotDir = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $BotDir "run.py"))) {
    Write-Host "Cannot find run.py next to $PSScriptRoot" -ForegroundColor Red
    exit 1
}

function Get-ConfigSetting([string]$file, [string]$key) {
    if (-not (Test-Path $file)) { return "" }
    $line = Select-String -Path $file -Pattern ("^\s*" + $key + "\s*=") -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $line) { return "" }
    return ($line.Line -replace "^[^=]*=\s*", "").Trim().Trim("'").Trim('"')
}

function Resolve-ServerRoot {
    if ($ServerRoot -and (Test-Path (Join-Path $ServerRoot "PalServer.exe"))) { return $ServerRoot }

    $candidates = @(
        (Join-Path $BotDir "config.local.json"),
        (Join-Path $BotDir "config.toml")
    )
    foreach ($file in $candidates) {
        if (-not (Test-Path $file)) { continue }
        $logPath = Get-ConfigSetting $file "log_path"
        if (-not $logPath) { continue }
        # ...\Pal\Binaries\Win64\ue4ss\UE4SS.log -> server root
        # ue4ss -> Win64 -> Binaries -> Pal -> server root（四层）
        $ue4ss = Split-Path -Parent $logPath
        $root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $ue4ss)))
        if (Test-Path (Join-Path $root "PalServer.exe")) { return $root }
    }
    return ""
}

function Resolve-Python {
    $embedded = Join-Path $BotDir "python\python.exe"
    if (Test-Path $embedded) { return $embedded }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return ""
}

$ServerRoot = Resolve-ServerRoot
$Python = Resolve-Python

$logDir = Join-Path $BotDir "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp       = Get-Date -Format "yyyyMMdd-HHmmss"
$launcherLog = Join-Path $logDir "launcher-$stamp.log"

function Write-Log($message) {
    Add-Content -Path $launcherLog -Value "$(Get-Date -Format 'HH:mm:ss') $message"
}

function Get-ServerProcess {
    Get-Process -Name "PalServer-Win64-Shipping-Cmd" -ErrorAction SilentlyContinue
}

function Test-Port($port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $client.Connect("127.0.0.1", $port)
        return $true
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

if (-not $Python) {
    Write-Host "Python not found. Put an embedded python in <bot>\python\ or install Python 3.11+." -ForegroundColor Red
    exit 1
}

if (-not $ServerRoot) {
    Write-Host "Server path not found. Run: python run.py wizard" -ForegroundColor Red
    exit 1
}

$RestPort = 8212
$restUrl = Get-ConfigSetting (Join-Path $BotDir "config.toml") "url"
if ($restUrl -match "127\.0\.0\.1:(\d+)") { $RestPort = [int]$Matches[1] }

if (-not (Get-ServerProcess)) {
    Write-Log "starting server: $ServerRoot"
    Start-Process -FilePath (Join-Path $ServerRoot "PalServer.exe") `
        -WorkingDirectory $ServerRoot -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $ServerRoot "server-stdout.log") `
        -RedirectStandardError (Join-Path $ServerRoot "server-stderr.log")
} else {
    Write-Log "server already running"
}

$ready = $false
for ($i = 0; $i -lt 120; $i++) {
    Start-Sleep -Seconds 2
    if (Test-Port $RestPort) {
        $ready = $true
        break
    }
}
Write-Log "rest ready: $ready"

$bot = Start-Process -FilePath $Python `
    -ArgumentList "run.py" `
    -WorkingDirectory $BotDir -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $logDir "bot-$stamp.log") `
    -RedirectStandardError (Join-Path $logDir "bot-$stamp.err.log")
Write-Log "bot started pid=$($bot.Id)"

while (Get-ServerProcess) {
    Start-Sleep -Seconds 15
}

Write-Log "server exited, stopping bot"
if ($bot -and -not $bot.HasExited) {
    Stop-Process -Id $bot.Id -Force -ErrorAction SilentlyContinue
}
Write-Log "done"
