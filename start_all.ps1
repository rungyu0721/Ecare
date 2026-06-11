param(
    [string]$TtsHost = "127.0.0.1",
    [int]$TtsPort = 8011,
    [double]$Speed = 1.0,
    [ValidateSet("subprocess", "runtime")]
    [string]$TtsBackend = "runtime"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Wait-ForHttp {
    param(
        [string]$Url,
        [string]$Name,
        [int]$MaxSeconds = 90
    )

    $waited = 0
    while ($waited -lt $MaxSeconds) {
        Start-Sleep -Seconds 2
        $waited += 2

        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2 -ErrorAction Stop
            if ($response.StatusCode -lt 400) {
                Write-Host "[OK] $Name is ready: $Url" -ForegroundColor Green
                return $true
            }
        } catch {
            # Keep waiting.
        }

        Write-Host "[INFO] Waiting for $Name... ${waited}s" -ForegroundColor DarkGray
    }

    Write-Warning "$Name was not ready after ${MaxSeconds}s: $Url"
    return $false
}

function Test-HttpReady {
    param([string]$Url)

    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2 -ErrorAction Stop
        return ($response.StatusCode -lt 400)
    } catch {
        return $false
    }
}

$ttsScript = Join-Path $Root "start_tts.ps1"
$backendScript = Join-Path $Root "start_backend.ps1"

if (-not (Test-Path $ttsScript)) {
    throw "start_tts.ps1 not found: $ttsScript"
}

if (-not (Test-Path $backendScript)) {
    throw "start_backend.ps1 not found: $backendScript"
}

$ttsHealthUrl = "http://$TtsHost`:$TtsPort/health"
if (Test-HttpReady -Url $ttsHealthUrl) {
    Write-Host "[OK] TTS service is already running: $ttsHealthUrl" -ForegroundColor Green
} else {
    Write-Host "[INFO] Starting TTS via start_tts.ps1..." -ForegroundColor Cyan
    $ttsCommand = "& '$ttsScript' -HostName '$TtsHost' -Port $TtsPort -Speed $Speed -Backend '$TtsBackend'"
    Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $ttsCommand

    Wait-ForHttp -Url $ttsHealthUrl -Name "TTS service" -MaxSeconds 90 | Out-Null
}

Write-Host "[INFO] Starting backend via start_backend.ps1..." -ForegroundColor Cyan
& $backendScript
