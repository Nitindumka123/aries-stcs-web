$ErrorActionPreference = "Continue"
Set-Location "C:\Users\dumka\OneDrive\Desktop\GUI"
$job = Start-Job -ScriptBlock {
  Set-Location "C:\Users\dumka\OneDrive\Desktop\GUI"
  python -m stcs_web.main 2>&1
}
Start-Sleep -Seconds 8
python shot_smoke.py 2>&1
Stop-Job -Id $job.Id
Remove-Job -Id $job.Id
Write-Output "SMOKE_DONE"
