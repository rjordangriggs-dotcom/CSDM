# Security Policy

## Supported Versions
Use the latest commit on `main` for security fixes.

## Reporting a Vulnerability
- Do not open public issues with exploit details.
- Report privately to the project maintainer with:
  - affected file/function
  - reproduction steps
  - impact assessment
  - suggested remediation (if available)

## Security Controls in This Project
- Receiver binds to localhost by default (`GPSD_BIND_HOST=127.0.0.1`).
- Signed beacon validation supported (`GPSD_BEACON_SECRET`, `GPSD_REQUIRE_SIGNATURE`).
- Request rate limiting and dedupe enabled.
- Runtime logs/evidence are ignored by git via `.gitignore`.
- SMTP password is expected via environment variable only.

## Operational Hardening Checklist
- Set a strong random `GPSD_BEACON_SECRET` in production.
- Set `GPSD_REQUIRE_SIGNATURE=true`.
- Keep tunnel private and do not expose receiver directly to internet.
- Rotate SMTP app passwords periodically and after any accidental disclosure.
- Restrict access to host filesystem and app data directory.
- Patch dependencies regularly.

## Data Handling
Evidence data may include IP, headers, timestamps, and geolocation estimates.
Store and process according to your local legal/privacy requirements.
