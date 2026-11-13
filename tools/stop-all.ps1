# Ask the Palworld server to shut down gracefully. The launcher will then
# notice the server is gone and stop the bot by itself.
#
# AdminPassword is read from PalWorldSettings.ini so there is one source of truth.
# Server path comes from config.toml (log_path) or -ServerRoot.

param(
    [string]$ServerRoot = ""
)

$BotDir = Split-Path -Parent $PSScriptRoot

if (-not $ServerRoot) {
    $config = Join-Path $BotDir "config.toml"
    if (Test-Path $config) {
        $line = Select-String -Path $config -Pattern "^\s*log_path\s*=" | Select-Object -First 1
        if ($line) {
            $logPath = ($line.Line -replace "^[^=]*=\s*", "").Trim().Trim("'").Trim('"')
            $ue4ss = Split-Path -Parent $logPath
            # ue4ss -> Win64 -> Binaries -> Pal -> server root（四层）
            $ServerRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $ue4ss)))
        }
    }
}

if (-not $ServerRoot) {
    Write-Host "server path unknown, pass -ServerRoot or run: python run.py wizard"
    exit 1
}

$ini = Join-Path $ServerRoot "Pal\Saved\Config\WindowsServer\PalWorldSettings.ini"

if (-not (Get-Process -Name "PalServer-Win64-Shipping-Cmd" -ErrorAction SilentlyContinue)) {
    Write-Host "server is not running, nothing to do"
    exit 0
}

if (-not (Test-Path $ini)) {
    Write-Host "cannot find $ini"
    exit 1
}

$raw = Get-Content $ini -Raw
$match = [regex]::Match($raw, 'AdminPassword="([^"]*)"')
$password = $match.Groups[1].Value
$auth = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("admin:$password"))
$body = '{"waittime":5,"message":"Server shutting down"}'

try {
    Invoke-WebRequest -Method Post -Uri "http://127.0.0.1:8212/v1/api/shutdown" `
        -Headers @{ Authorization = "Basic $auth" } `
        -ContentType "application/json" -Body $body -TimeoutSec 10 -UseBasicParsing | Out-Null
    Write-Host "shutdown requested, waiting for the server to exit..."
} catch {
    Write-Host "shutdown failed: $($_.Exception.Message)"
    exit 1
}

for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 2
    if (-not (Get-Process -Name "PalServer-Win64-Shipping-Cmd" -ErrorAction SilentlyContinue)) {
        Write-Host "server stopped"
        exit 0
    }
}
Write-Host "server did not exit in 60s, check manually"
exit 1
