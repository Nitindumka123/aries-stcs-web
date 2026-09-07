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

function Check-Page($name, $url) {
  $r = Invoke-WebRequest -Uri $url -WebSession $s -UseBasicParsing -MaximumRedirection 2 -ErrorAction Stop
  $c = $r.Content
  $issues = @()
  if ($c -match '\{\{|\{%') { $issues += "UNRENDERED_JINJA" }
  if (!($c -match '/static/app.css')) { $issues += "NO_CSS" }
  if (!($c -match 'stcs-csrf-token')) { $issues += "NO_CSRF_META" }
  if (!($c -match 'class="app"')) { $issues += "NO_APP_SHELL" }
  if (!($c -match 'topnav')) { $issues += "NO_TOPNAV" }
  if ($issues.Count -eq 0) { Write-Output ("CHECK " + $name + ": OK bytes=" + $c.Length) }
  else { Write-Output ("CHECK " + $name + ": " + ($issues -join ",")) }
}
Check-Page "control" "http://127.0.0.1:8000/app/control"
Check-Page "observations" "http://127.0.0.1:8000/app/observations"
Check-Page "camera" "http://127.0.0.1:8000/app/camera"
Check-Page "system" "http://127.0.0.1:8000/app/system"
Check-Page "admin" "http://127.0.0.1:8000/app/admin"
foreach ($u in @("/app/checkup","/app/history","/app/syscam")) {
  $r = Invoke-WebRequest -Uri ("http://127.0.0.1:8000" + $u) -WebSession $s -UseBasicParsing -ErrorAction Stop
  Write-Output ("REDIRECT " + $u + " -> " + $r.BaseResponse.ResponseUri.AbsolutePath)
}
Stop-Job $job; Remove-Job $job
Write-Output "STRUCT_CHECKS_DONE"
