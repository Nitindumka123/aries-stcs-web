$ErrorActionPreference = "Continue"
Set-Location "C:\Users\dumka\OneDrive\Desktop\GUI"
$job = Start-Job -ScriptBlock {
  Set-Location "C:\Users\dumka\OneDrive\Desktop\GUI"
  python -m stcs_web.main 2>&1
}
$ok = $false
for ($i = 0; $i -lt 20; $i++) {
  Start-Sleep -Seconds 1
  try {
    $h = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -TimeoutSec 3 -UseBasicParsing
    if ($h.StatusCode -eq 200) { $ok = $true; break }
  } catch { }
}
if (-not $ok) { Stop-Job $job; Remove-Job $job; throw "no server" }
$s = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$pg = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/login" -WebSession $s -UseBasicParsing
if ($pg.Content -match 'name="_stcs_csrf_token" value="([^"]+)"') { $csrf = $Matches[1] } else { throw "no csrf" }
Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/login" -WebSession $s -Method POST -UseBasicParsing `
  -Body @{username="Admin"; password="Admin@123"; _stcs_csrf_token=$csrf} -MaximumRedirection 0 -ErrorAction SilentlyContinue | Out-Null
foreach ($f in @("csv","xlsx","pdf","json")) {
  try {
    $r = Invoke-WebRequest -Uri ("http://127.0.0.1:8000/api/history/export?fmt=" + $f) -WebSession $s -UseBasicParsing -ErrorAction Stop
    Write-Output ("EXPORT " + $f + ": " + $r.StatusCode + " type=" + $r.Headers["Content-Type"] + " len=" + $r.RawContentLength)
  } catch {
    Write-Output ("EXPORT " + $f + " FAILED: " + $_.Exception.Message)
  }
}
try {
  $h2 = Invoke-WebRequest -Uri "http://127.0.0.1:8000/app/history?from=2026-08-01&q=M51&obs=99999" -WebSession $s -UseBasicParsing -ErrorAction Stop
  Write-Output ("HISTORY_FILTERED: " + $h2.StatusCode + " has-cal=" + ($h2.Content -match 'Last 7 days'))
} catch { Write-Output ("HISTORY_FILTERED FAILED: " + $_.Exception.Message) }
Stop-Job $job; Remove-Job $job
Write-Output "EXPORT_TESTS_DONE"
