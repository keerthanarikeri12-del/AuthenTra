$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
if (-not $nodeCommand) {
    $bundledNode = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
    if (Test-Path -LiteralPath $bundledNode) { $nodePath = $bundledNode } else { throw 'Install Node.js before starting AuthenTra.' }
} else { $nodePath = $nodeCommand.Source }
$env:NODE_BINARY = $nodePath
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Run the installation steps in README.md first.' }
New-Item -ItemType Directory -Path '.local' -Force | Out-Null
if (-not (Test-NetConnection -ComputerName 127.0.0.1 -Port 8545 -InformationLevel Quiet -WarningAction SilentlyContinue)) {
    $chainProcess = Start-Process -FilePath $nodePath -ArgumentList 'scripts/chain.mjs' -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput '.local/chain.log' -RedirectStandardError '.local/chain-error.log' -PassThru
    $chainProcess.Id | Set-Content '.local/chain.pid'
    $chainReady = $false
    for ($attempt=0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 1
        if (Test-Path -LiteralPath '.local/chain.log') {
            if (Select-String -LiteralPath '.local/chain.log' -Pattern 'blockchain ready' -Quiet) { $chainReady = $true; break }
        }
        if ($chainProcess.HasExited) { throw 'The blockchain did not start. See .local/chain-error.log.' }
    }
    if (-not $chainReady) { throw 'Blockchain startup timed out. See .local/chain-error.log.' }
}
& $nodePath scripts/chain.mjs --check
if ($LASTEXITCODE -ne 0) { throw 'Blockchain readiness check failed. See the error above.' }
& $pythonPath -c "from backend.documents import model_ready; raise SystemExit(0 if model_ready() else 1)"
if ($LASTEXITCODE -ne 0) {
    if (Test-Path -LiteralPath '.local/model.joblib') { throw 'The advisory model cannot load. Retrain it with .venv/Scripts/python.exe scripts/train_model.py using the documented Python environment.' }
    & $pythonPath scripts/train_model.py
    if ($LASTEXITCODE -ne 0) { throw 'The AI model setup failed.' }
}
& $pythonPath scripts/seed_demo.py
if ($LASTEXITCODE -ne 0) { throw 'The sample certificate setup failed.' }
# Build from the current sources so an old dist cannot hide fixes.
& $nodePath node_modules/vite/bin/vite.js build
if ($LASTEXITCODE -ne 0) { throw 'The frontend build failed.' }
$alreadyRunning = $false
try { $health = Invoke-RestMethod 'http://127.0.0.1:8000/api/health'; $alreadyRunning = $health.demo -eq $true -and $health.status -eq 'ready' -and $health.blockchain -eq $true -and $health.database -eq $true -and $health.model -eq $true } catch {}
if (-not $alreadyRunning) {
    $serverProcess = Start-Process -FilePath $pythonPath -ArgumentList 'scripts/server.py' -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput '.local/server.log' -RedirectStandardError '.local/server-error.log' -PassThru
    $serverProcess.Id | Set-Content '.local/server.pid'
    $applicationReady = $false
    for ($attempt=0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 1
        try { $health = Invoke-RestMethod 'http://127.0.0.1:8000/api/health'; if ($health.demo -eq $true -and $health.status -eq 'ready' -and $health.blockchain -eq $true -and $health.database -eq $true -and $health.model -eq $true) { $applicationReady = $true; break } } catch {}
        if ($serverProcess.HasExited) { throw 'The application did not start. See .local/server-error.log.' }
    }
    if (-not $applicationReady) { throw 'Application readiness timed out. See .local/server-error.log.' }
}
Write-Host 'AuthenTra is available at http://127.0.0.1:8000'
Write-Host 'Use the User, Institution or Admin portal with the demo credentials documented in README.md.'
