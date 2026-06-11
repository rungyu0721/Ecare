param(
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8011,
    [string]$PromptWav = "scripts\data\tts_prompt_ecare.wav",
    [string]$PromptText = "",
    [double]$Speed = 1.0,
    [ValidateSet("subprocess", "runtime")]
    [string]$Backend = "runtime"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$DefaultPromptTextBase64 = "5oKo5aW977yM5oiR5piv57Sn5oCl5Yqp5omL44CC6K+35L+d5oyB5Ya36Z2Z77yM5oiR5Lya5LiA5q2l5LiA5q2l5Y2P5Yqp5oKo56Gu6K6k546w5Zy654q25Ya144CC6K+35YWI5rOo5oSP6Ieq6Lqr5a6J5YWo77yM5bm25L6d54Wn55S76Z2i5o+Q56S65Zue5oql5pyA5paw5Y+Y5YyW44CC"
if ([string]::IsNullOrWhiteSpace($PromptText)) {
    $PromptText = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($DefaultPromptTextBase64))
}

$Python = Join-Path $Root ".venv-tts\Scripts\python.exe"
$ServiceScript = Join-Path $Root "scripts\tts\serve_tts.py"

if ([System.IO.Path]::IsPathRooted($PromptWav)) {
    $PromptWavPath = $PromptWav
} else {
    $PromptWavPath = Join-Path $Root $PromptWav
}

if (-not (Test-Path $Python)) {
    Write-Error "TTS Python not found: $Python. Create .venv-tts and install TTS dependencies first."
}

if (-not (Test-Path $ServiceScript)) {
    Write-Error "TTS service script not found: $ServiceScript"
}

if (-not (Test-Path $PromptWavPath)) {
    Write-Error "Prompt wav not found: $PromptWavPath. Convert your prompt mp3 to scripts\data\tts_prompt_ecare.wav first."
}

Write-Host "Starting E-CARE local TTS service..."
Write-Host "URL: http://$HostName`:$Port"
Write-Host "Prompt wav: $PromptWavPath"
Write-Host "Backend: $Backend"
Write-Host "Press Ctrl+C to stop."

& $Python $ServiceScript `
    --host $HostName `
    --port $Port `
    --prompt-wav $PromptWavPath `
    --prompt-text $PromptText `
    --speed $Speed `
    --backend $Backend
