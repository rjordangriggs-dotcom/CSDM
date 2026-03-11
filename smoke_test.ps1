param(
    [string]$PythonExe = "python",
    [int]$StartupWaitSeconds = 10
)

$ErrorActionPreference = "Stop"

function Invoke-PythonJson {
    param([string]$Code)
    $output = $Code | & $PythonExe -
    if (-not $output) {
        throw "Python command returned no output."
    }
    return $output | ConvertFrom-Json
}

function Test-ListenerReady {
    param([int]$Port, [string]$Timestamp)
    try {
        $uri = "http://127.0.0.1:$Port/log?src=healthcheck.html&subj=healthcheck&ts=$Timestamp"
        $resp = Invoke-WebRequest -Uri $uri -UseBasicParsing -TimeoutSec 2
        return ($resp.StatusCode -eq 200)
    }
    catch {
        return $false
    }
}

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$token = "smoke-" + [Guid]::NewGuid().ToString("N")
$ts = (Get-Date).ToString("o")

Write-Host "[smoke] repo: $repoRoot"
Write-Host "[smoke] token: $token"

$meta = Invoke-PythonJson @'
import json
import beacon_receiver as b
print(json.dumps({"app_dir": str(b.APP_DIR), "db": str(b.DB_FILE), "port": int(b.LISTEN_PORT)}))
'@

$port = [int]$meta.port
$dbPath = [string]$meta.db
$appDir = [string]$meta.app_dir

Write-Host "[smoke] app dir: $appDir"
Write-Host "[smoke] db path: $dbPath"
Write-Host "[smoke] listener port: $port"

$listener = $null
$startedByScript = $false

try {
    $ready = Test-ListenerReady -Port $port -Timestamp $ts

    if (-not $ready) {
        Write-Host "[smoke] listener not detected, starting beacon_receiver.py"
        $listener = Start-Process -FilePath $PythonExe -ArgumentList "beacon_receiver.py" -WorkingDirectory $repoRoot -PassThru
        $startedByScript = $true

        for ($i = 0; $i -lt $StartupWaitSeconds; $i++) {
            Start-Sleep -Seconds 1

            if ($listener.HasExited) {
                throw "Listener process exited early (code=$($listener.ExitCode))."
            }

            if (Test-ListenerReady -Port $port -Timestamp $ts) {
                $ready = $true
                break
            }
        }
    }

    if (-not $ready) {
        throw "Listener did not become ready on port $port within $StartupWaitSeconds seconds."
    }

    $uri = "http://127.0.0.1:$port/log?src=smoke_test.html&subj=$token&ts=$ts"
    $result = Invoke-WebRequest -Uri $uri -UseBasicParsing -TimeoutSec 5
    if ($result.StatusCode -ne 200) {
        throw "Beacon request failed with HTTP $($result.StatusCode)"
    }
    Write-Host "[smoke] beacon request returned HTTP 200"

    Start-Sleep -Milliseconds 600

    $countObj = Invoke-PythonJson @"
import json, sqlite3
db = r'''$dbPath'''
token = r'''$token'''
conn = sqlite3.connect(db)
cur = conn.cursor()
cur.execute("SELECT COUNT(*) FROM alerts WHERE subject = ?", (token,))
count = cur.fetchone()[0]
conn.close()
print(json.dumps({"count": int(count)}))
"@

    if ([int]$countObj.count -lt 1) {
        throw "No DB row found for smoke token '$token'."
    }

    Write-Host "[smoke] PASS: beacon row inserted (count=$($countObj.count))"
    if ($startedByScript) {
        Write-Host "[smoke] listener was started by this script"
    } else {
        Write-Host "[smoke] listener was already running"
    }
}
finally {
    if ($startedByScript -and $listener -and -not $listener.HasExited) {
        Stop-Process -Id $listener.Id -Force
        Write-Host "[smoke] listener stopped"
    }
}
