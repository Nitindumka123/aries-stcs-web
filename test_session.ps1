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
# Simulate 3 consecutive refreshes / navigations on the SAME session
$users = @()
foreach ($n in 1..3) {
  $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/app/control" -WebSession $s -UseBasicParsing -MaximumRedirection 2 -ErrorAction Stop
  $c = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/auth/check" -WebSession $s -UseBasicParsing -ErrorAction Stop
  $users += $c.Content
  Write-Output ("REFRESH " + $n + ": page=" + $r.StatusCode + " auth=" + $c.Content)
}
if (($users | Select-Object -Unique).Count -eq 1 -and $users[0] -match '"authenticated":true') {
  Write-Output "SESSION_PERSISTS_ACROSS_REFRESH: True"
} else {
  Write-Output "SESSION_PERSISTS_ACROSS_REFRESH: False (FAIL)"
}
Stop-Job $job; Remove-Job $job
Write-Output "SESSION_TEST_DONE"
