# Cloud Sync Decoy Monitor

Cloud Sync Decoy Monitor is a desktop utility that deploys decoy files into synced cloud folders (for example OneDrive/Google Drive) and records beacon callbacks when those files are opened.

## What it does
- Deploys HTML/PDF decoy files to discovered sync folders.
- Embeds beacon callbacks in generated HTML decoys.
- Runs a local receiver to log alert events.
- Stores events in SQLite and JSON evidence files.
- Supports optional signed beacons (`HMAC-SHA256`) for request authenticity.
- Supports rate limiting, dedupe, and retention pruning.

## Project status
This project is currently released under Apache-2.0 (free/open source).

Licensing note for future versions:
- Future releases may use a different license (including commercial licensing).
- This specific released version remains under Apache-2.0.

## Repository layout
- `aisv_main.py`: GUI app (setup, deployment, quick operations)
- `beacon_receiver.py`: local alert receiver and evidence writer
- `randomizers.py`: decoy filename/subject randomization
- `receiver_config.template.json`: receiver configuration template
- `smoke_test.ps1`: end-to-end smoke test helper
- `SECURITY.md`: security reporting and hardening notes
- `RELEASE_CHECKLIST.md`: pre-release checklist

## Requirements
- Windows + Python 3.11+ recommended
- Cloudflare Tunnel (`cloudflared`) for public endpoint routing

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

## Quick start
1. Start receiver.
2. Start app.
3. Run quick setup.
4. Deploy decoys.

### Start receiver (PowerShell)

```powershell
$env:GPSD_SMTP_HOST="smtp.yourprovider.com"
$env:GPSD_SMTP_PORT="587"
$env:GPSD_SMTP_TLS_MODE="starttls"
$env:GPSD_SMTP_USERNAME="alerts@yourdomain.com"
$env:GPSD_SMTP_FROM="alerts@yourdomain.com"
$env:GPSD_SECONDARY_EMAIL="you@yourdomain.com"
$env:GPSD_SMTP_PASSWORD="your-secret-password"
$env:GPSD_BEACON_SECRET="set-a-long-random-secret"
$env:GPSD_REQUIRE_SIGNATURE="true"
$env:GPSD_BIND_HOST="127.0.0.1"
python beacon_receiver.py
```

### Start app

```powershell
python aisv_main.py
```

In the UI:
- Click `Quick Setup (Recommended)`
- Optionally click `Validate Setup`
- Click `Start Monitoring`
- Optionally click `Start All Services` to launch receiver+tunnel from UI

## Beacon URL
Set beacon URL to your tunnel endpoint, for example:

```text
https://defense.01ai.ai/log
```

## Environment variables
Core receiver vars:
- `GPSD_SMTP_HOST`
- `GPSD_SMTP_PORT`
- `GPSD_SMTP_TLS_MODE` (`ssl`, `starttls`, `plain`)
- `GPSD_SMTP_USERNAME`
- `GPSD_SMTP_FROM`
- `GPSD_SECONDARY_EMAIL`
- `GPSD_SMTP_PASSWORD`

Security/hardening vars:
- `GPSD_BEACON_SECRET` (recommended)
- `GPSD_REQUIRE_SIGNATURE` (`true` / `false`)
- `GPSD_BIND_HOST` (default `127.0.0.1`)
- `GPSD_RATE_LIMIT_WINDOW_SEC`
- `GPSD_RATE_LIMIT_MAX_PER_IP`
- `GPSD_DEDUPE_WINDOW_SEC`
- `GPSD_RETENTION_DAYS`
- `GPSD_MAX_EVIDENCE_FILES`

Optional vars:
- `GPSD_TUNNEL_URL`
- `GPSD_LISTEN_PORT`

## Data location
Runtime artifacts are stored in:
- `%LOCALAPPDATA%\CloudSyncDecoyMonitor` when writable
- fallback: `./.gpsdefense_data`

Includes:
- `config.json`
- `sys_integrity.log`
- `security_suite.db`
- `evidence/*.json`
- `receiver_run.log`
- `tunnel_run.log`

## Smoke test

```powershell
powershell -ExecutionPolicy Bypass -File .\smoke_test.ps1
```

## Security notes
- Do not commit runtime logs, DBs, or evidence artifacts.
- Rotate credentials immediately after accidental exposure.
- Keep tunnel private and avoid direct internet exposure of receiver host.
- Use signed beacons in production.

## Legal notice
You are responsible for operating this software in compliance with applicable laws, privacy requirements, and consent obligations in your jurisdiction.
