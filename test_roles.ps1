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

# Scientist login
$s = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$pg = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/login" -WebSession $s -UseBasicParsing
if ($pg.Content -match 'name="_stcs_csrf_token" value="([^"]+)"') { $csrf = $Matches[1] } else { throw "no csrf" }
$resp = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/login" -WebSession $s -Method POST -UseBasicParsing `
  -Body @{username="Scientist1"; password="Pass@123"; _stcs_csrf_token=$csrf} -MaximumRedirection 0 -ErrorAction SilentlyContinue
Write-Output ("SCIENTIST_LOGIN: " + $resp.StatusCode + " -> " + $resp.Headers.Location)
$chk = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/auth/check" -WebSession $s -UseBasicParsing
Write-Output ("SCIENTIST_AUTH: " + $chk.Content)

# Scientist CAN open control/history/camera/system
foreach ($p in @("control","observations","camera","system")) {
  try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/app/$p" -WebSession $s -UseBasicParsing -MaximumRedirection 2 -ErrorAction Stop
    Write-Output ("SCIENTIST /app/$p : " + $r.StatusCode)
  } catch { Write-Output ("SCIENTIST /app/$p FAILED: " + $_.Exception.Message) }
}

# Scientist CANNOT open admin workspace (redirect to login)
$a = Invoke-WebRequest -Uri "http://127.0.0.1:8000/app/admin" -WebSession $s -UseBasicParsing -MaximumRedirection 0 -ErrorAction SilentlyContinue
Write-Output ("SCIENTIST /app/admin: " + $a.StatusCode + " -> " + $a.Headers.Location)

# Scientist CANNOT list users (403)
try {
  Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/users" -WebSession $s -UseBasicParsing -ErrorAction Stop | Out-Null
  Write-Output "SCIENTIST /api/users: NOT_DENIED (FAIL)"
} catch {
  Write-Output ("SCIENTIST /api/users denied: " + $_.Exception.Response.StatusCode.value__)
}

# Logout CSRF missing rejected, then proper logout
$bad = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/logout" -WebSession $s -Method POST -UseBasicParsing `
  -Body @{} -ErrorAction SilentlyContinue
Write-Output ("LOGOUT_NO_CSRF_REJECTED: " + ($bad.Content -match 'Invalid CSRF token'))
$dash = Invoke-WebRequest -Uri "http://127.0.0.1:8000/app/control" -WebSession $s -UseBasicParsing -MaximumRedirection 0 -ErrorAction SilentlyContinue
Write-Output ("DASH_CSRF_META: " + ($dash.Content -match 'name="stcs-csrf-token" content="([a-f0-9]{64})"'))
if ($dash.Content -match 'name="stcs-csrf-token" content="([^"]+)"') { $ct = $Matches[1] }
Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/logout" -WebSession $s -Method POST -UseBasicParsing `
  -Body @{_stcs_csrf_token=$ct} -MaximumRedirection 0 -ErrorAction SilentlyContinue | Out-Null
$after = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/auth/check" -WebSession $s -UseBasicParsing
Write-Output ("SCIENTIST_AFTER_LOGOUT: " + $after.Content)

Stop-Job $job; Remove-Job $job
Write-Output "ROLE_TESTS_DONE"
