param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [int]$Runs = 3
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Net.Http
$httpClient = [System.Net.Http.HttpClient]::new()

$scenarios = @(
    @{
        Name = "short"
        JsonBody = '{"messages":[{"role":"user","content":"\u9644\u8fd1\u6709\u4eba\u6253\u67b6"}]}'
    },
    @{
        Name = "followup"
        JsonBody = '{"messages":[{"role":"assistant","content":"\u8acb\u554f\u4e8b\u767c\u5730\u9ede\u5728\u54ea\u88e1\uff1f"},{"role":"user","content":"\u5728\u53f0\u5317\u8eca\u7ad9\u5357\u4e8c\u9580"}]}'
    },
    @{
        Name = "high_risk"
        JsonBody = '{"messages":[{"role":"user","content":"\u6709\u4eba\u6d41\u8840\u5012\u5728\u5730\u4e0a\uff0c\u73fe\u5728\u5728\u53f0\u5317\u8eca\u7ad9\u5357\u4e8c\u9580"}]}'
    }
)

foreach ($scenario in $scenarios) {
    Write-Host "=== Scenario: $($scenario.Name) ===" -ForegroundColor Cyan
    $durations = @()

    for ($i = 1; $i -le $Runs; $i++) {
        $json = $scenario.JsonBody
        $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()

        try {
            $content = [System.Net.Http.StringContent]::new(
                $json,
                [System.Text.Encoding]::UTF8,
                "application/json"
            )
            $httpResponse = $httpClient.PostAsync("$BaseUrl/chat", $content).GetAwaiter().GetResult()
            $rawBody = $httpResponse.Content.ReadAsStringAsync().GetAwaiter().GetResult()

            if (-not $httpResponse.IsSuccessStatusCode) {
                throw $rawBody
            }

            $response = $rawBody | ConvertFrom-Json

            $stopwatch.Stop()
            $durations += $stopwatch.ElapsedMilliseconds

            $reply = ""
            if ($null -ne $response.reply) {
                $reply = [string]$response.reply
            }
            if ($reply.Length -gt 60) {
                $reply = $reply.Substring(0, 60) + "..."
            }

            Write-Host (
                "Run {0}: {1} ms | risk={2} | reply={3}" -f
                $i,
                $stopwatch.ElapsedMilliseconds,
                $response.risk_level,
                $reply
            )
        } catch {
            $stopwatch.Stop()
            $detail = $_.ErrorDetails.Message
            if ([string]::IsNullOrWhiteSpace($detail)) {
                $detail = $_.Exception.Message
            }
            Write-Error ("Run {0} failed: {1}" -f $i, $detail)
        }
    }

    if ($durations.Count -gt 0) {
        $average = [Math]::Round((($durations | Measure-Object -Average).Average), 2)
        $minimum = ($durations | Measure-Object -Minimum).Minimum
        $maximum = ($durations | Measure-Object -Maximum).Maximum
        Write-Host "Average: $average ms | Min: $minimum ms | Max: $maximum ms" -ForegroundColor Green
    }

    Write-Host ""
}

if ($null -ne $httpClient) {
    $httpClient.Dispose()
}
