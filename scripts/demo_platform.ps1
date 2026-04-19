# AI4ML local API smoke test. Open http://localhost:5173 in browser for UI.
$ErrorActionPreference = "Stop"
$Base = "http://127.0.0.1:8000/api"

Write-Host "== Health =="
(Invoke-WebRequest -UseBasicParsing -TimeoutSec 8 "$Base/health").Content

Write-Host ""
Write-Host "== Login (admin) =="
$loginBody = @{ username = "admin"; password = "admin123" } | ConvertTo-Json
$loginResp = Invoke-WebRequest -UseBasicParsing -TimeoutSec 8 -Method Post -ContentType "application/json" -Body $loginBody "$Base/auth/login"
$token = ($loginResp.Content | ConvertFrom-Json).access_token
Write-Host "OK, token length:" $token.Length

Write-Host ""
Write-Host "== Users (admin) =="
$headers = @{ Authorization = "Bearer $token" }
(Invoke-WebRequest -UseBasicParsing -TimeoutSec 8 -Headers $headers "$Base/users").Content

Write-Host ""
Write-Host "== Tasks =="
(Invoke-WebRequest -UseBasicParsing -TimeoutSec 8 "$Base/tasks").Content

Write-Host ""
Write-Host "Done. Open http://localhost:5173 and sign in as admin / admin123 to open Admin tab."
