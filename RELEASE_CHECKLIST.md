# Release Checklist

## Pre-Release Security
- [ ] Confirm no real credentials are in source/config/docs.
- [ ] Confirm `.gitignore` includes logs/db/evidence/local secrets.
- [ ] Regenerate any credentials previously shared in chat/terminal history.
- [ ] Set/verify production env vars (`GPSD_*`).

## Functional Checks
- [ ] `python -m compileall aisv_main.py beacon_receiver.py randomizers.py`
- [ ] Run receiver locally and confirm startup on expected host/port.
- [ ] Run smoke test: `powershell -ExecutionPolicy Bypass -File .\\smoke_test.ps1`
- [ ] Validate decoy deployment to sync folders.
- [ ] Validate signed beacon ingestion and DB/evidence writes.

## Packaging
- [ ] Install deps: `python -m pip install -r requirements.txt`
- [ ] Build executables (if applicable).
- [ ] Run basic startup test for built artifacts.

## Repository Hygiene
- [ ] Review `git status` for unexpected files.
- [ ] Review `git diff --staged` before commit.
- [ ] Update `README.md` if setup changed.
- [ ] Tag release/version after successful tests.
