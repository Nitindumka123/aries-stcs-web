$ErrorActionPreference = "Stop"
Set-Location "C:\Users\dumka\OneDrive\Desktop\GUI"
$job = Start-Job -ScriptBlock {
  Set-Location "C:\Users\dumka\OneDrive\Desktop\GUI"
  python -m stcs_web.main
}
$ok = $false
for ($i = 0; $i -lt 25; $i++) {
  Start-Sleep -Seconds 1
  try {
    $h = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -TimeoutSec 3 -UseBasicParsing
    if ($h.StatusCode -eq 200) { $ok = $true; break }
  } catch { }
}
if (-not $ok) {
  Receive-Job $job | Out-String | Write-Output
  Stop-Job $job; Remove-Job $job
  throw "server did not start"
}
Write-Output ("HEALTH: " + $h.Content)

# 1. Login page renders with CSRF token
$login = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/login" -SessionVariable sess -UseBasicParsing
$hasToken = $login.Content -match '_stcs_csrf_token'
Write-Output ("LOGIN_PAGE_CSRF_FIELD: " + $hasToken)
if ($login.Content -match 'name="_stcs_csrf_token" value="([^"]+)"') { $csrf = $Matches[1] } else { throw "no csrf token in login page" }
Write-Output ("CSRF_LEN: " + $csrf.Length)

# 2. Wrong password rejected (with valid CSRF)
$bad = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/login" -WebSession $sess -Method POST -UseBasicParsing `
  -Body @{username="Admin"; password="wrong"; _stcs_csrf_token=$csrf}
Write-Output ("BAD_LOGIN_HAS_ERROR: " + ($bad.Content -match 'Invalid username or password'))

# 3. Missing CSRF on login rejected (re-rendered 200 + error text)
$noc = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/login" -SessionVariable s2 -UseBasicParsing | Out-Null
$nocResp = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/login" -WebSession $s2 -Method POST -UseBasicParsing `
  -Body @{username="Admin"; password="Admin@123"}
Write-Output ("CSRF_MISSING_LOGIN_REJECTED: " + ($nocResp.Content -match 'Invalid CSRF token'))
$pg2 = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/login" -WebSession $s2 -UseBasicParsing
if ($pg2.Content -match 'name="_stcs_csrf_token" value="([^"]+)"') { $csrf2 = $Matches[1] } else { throw "no csrf token page2" }

# 4. Real login (fallback dev credentials)
$resp = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/login" -WebSession $s2 -Method POST -UseBasicParsing `
  -Body @{username="Admin"; password="Admin@123"; _stcs_csrf_token=$csrf2} -MaximumRedirection 0 -ErrorAction SilentlyContinue
Write-Output ("LOGIN_STATUS: " + $resp.StatusCode + " -> " + $resp.Headers.Location)
if ($resp.StatusCode -eq 200) {
  Write-Output ("LOGIN_PAGE_SNIPPET: " + $resp.Content.Substring(0, [Math]::Min(300, $resp.Content.Length)))
}

# 5. Auth check after login
$chk = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/auth/check" -WebSession $s2 -UseBasicParsing
Write-Output ("AUTH_CHECK: " + $chk.Content)

# 6. Workspace pages (authenticated) — no follow, show hop chain manually
foreach ($p in @("control","observations","camera","system","admin")) {
  try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/app/$p" -WebSession $s2 -UseBasicParsing -MaximumRedirection 2 -ErrorAction Stop
    $nav = $r.Content -match 'OBSERVATIONS'
    Write-Output ("PAGE /app/$p : " + $r.StatusCode + " topnav=" + $nav)
  } catch {
    Write-Output ("PAGE /app/$p FAILED: " + $_.Exception.Message)
  }
}

# 7. Unauthenticated workspace redirects
$u = Invoke-WebRequest -Uri "http://127.0.0.1:8000/app/control" -UseBasicParsing -MaximumRedirection 0 -ErrorAction SilentlyContinue
Write-Output ("UNAUTH_CONTROL: " + $u.StatusCode + " -> " + $u.Headers.Location)

# 8. Snapshot API requires auth
try {
  Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/telemetry/snapshot" -UseBasicParsing -ErrorAction Stop | Out-Null
  Write-Output "SNAPSHOT_UNAUTH: NOT_REJECTED (FAIL)"
} catch { Write-Output "SNAPSHOT_UNAUTH: 401 as expected" }
$snap = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/telemetry/snapshot" -WebSession $s2 -UseBasicParsing
Write-Output ("SNAPSHOT_AUTH: " + $snap.Content.Substring(0, [Math]::Min(220, $snap.Content.Length)))

# 9. Command validation (no motion): needs CSRF header? form post with token
$dash = Invoke-WebRequest -Uri "http://127.0.0.1:8000/app/control" -WebSession $s2 -UseBasicParsing
if ($dash.Content -match 'name="stcs-csrf-token" content="([^"]+)"') { $ct = $Matches[1] } else { throw "no dashboard csrf meta" }
$val = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/command/validate" -WebSession $s2 -Method POST -UseBasicParsing `
  -Body @{command="slewtocoordinatesasync"; ra_deg="189.2"; dec_deg="27.3"; _stcs_csrf_token=$ct}
Write-Output ("CMD_VALIDATE: " + $val.Content.Substring(0, [Math]::Min(220, $val.Content.Length)))
try {
  Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/command/validate" -WebSession $s2 -Method POST -UseBasicParsing `
    -Body @{command="bogus_cmd"; _stcs_csrf_token=$ct} -ErrorAction Stop | Out-Null
  Write-Output "CMD_BAD: NOT_REJECTED (FAIL)"
} catch { Write-Output "CMD_BAD: rejected as expected" }

# 10. Static CSS
$css = Invoke-WebRequest -Uri "http://127.0.0.1:8000/static/app.css" -UseBasicParsing
Write-Output ("STATIC_CSS: " + $css.StatusCode + " len=" + $css.RawContentLength)

# 11. Logout with CSRF then verify protected route rejects
Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/logout" -WebSession $s2 -Method POST -UseBasicParsing `
  -Body @{_stcs_csrf_token=$ct} -MaximumRedirection 0 -ErrorAction SilentlyContinue | Out-Null
$after = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/auth/check" -WebSession $s2 -UseBasicParsing
Write-Output ("AUTH_AFTER_LOGOUT: " + $after.Content)

Stop-Job $job; Remove-Job $job
Write-Output "PHASE2_RUNTIME_TESTS_DONE"
