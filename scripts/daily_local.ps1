# 종가배팅 장마감 후 자동 루틴: universe → refresh → scan → export → notify
# 예약 작업(ClosingBet-Daily, 평일 15:40)에서 호출. 수동 실행도 가능.
param(
    [string]$ProjectDir = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Continue"
$ts = Get-Date -Format "yyyyMMdd"
$logDir = Join-Path $ProjectDir "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logFile = Join-Path $logDir "daily_$ts.log"

function WLog([string]$msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -LiteralPath $logFile -Value $line -Encoding UTF8
    Write-Host $line
}

# .env 로드 (TELEGRAM_BOT_TOKEN 등 — .env는 gitignore 대상)
$envFile = Join-Path $ProjectDir ".env"
if (Test-Path $envFile) {
    Get-Content -LiteralPath $envFile -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $i = $line.IndexOf("=")
            $k = $line.Substring(0, $i).Trim()
            $v = $line.Substring($i + 1).Trim().Trim('"').Trim("'")
            [Environment]::SetEnvironmentVariable($k, $v, "Process")
        }
    }
    WLog ".env 로드 완료"
} else {
    WLog "WARNING: .env 없음 — 알림 채널 환경변수 미설정 상태로 실행"
}

Set-Location -LiteralPath $ProjectDir
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$steps = @(
    @{ name = "universe"; args = @("universe"); optional = $true },
    @{ name = "refresh";  args = @("refresh");  optional = $false },
    @{ name = "scan";     args = @("scan");    optional = $false },
    @{ name = "export";   args = @("export");   optional = $false },
    @{ name = "notify";   args = @("notify");   optional = $false }
)

$failed = @()
foreach ($s in $steps) {
    WLog "==== $($s.name) 시작 ===="
    $out = & python run.py @($s.args) 2>&1 | ForEach-Object { "$_" }
    $code = $LASTEXITCODE
    $out | ForEach-Object { Add-Content -LiteralPath $logFile -Value "  $_" -Encoding UTF8 }
    $out | Select-Object -Last 5 | Write-Host
    if ($code -ne 0) {
        WLog "FAIL $($s.name) (exit $code)"
        if (-not $s.optional) { $failed += $s.name; if ($s.name -eq "refresh") { break } }
    } else {
        WLog "OK   $($s.name)"
    }
    Start-Sleep -Seconds 2
}

if ($failed.Count) {
    WLog "일부 실패: $($failed -join ', ') — 로그 참조 $logFile"
    exit 1
}
WLog "전체 완료"
exit 0
