import hashlib
import hmac
import json
import os
import smtplib
import sqlite3
import threading
import time
import urllib.parse
from collections import defaultdict, deque
from datetime import datetime, timezone
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from uuid import uuid4

import requests


def resolve_app_dir() -> Path:
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "CloudSyncDecoyMonitor",
        Path(__file__).resolve().parent / ".gpsdefense_data",
    ]
    for candidate in candidates:
        if not str(candidate).strip():
            continue
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write_probe"
            with open(probe, "w", encoding="utf-8") as f:
                f.write("ok")
            probe.unlink(missing_ok=True)
            return candidate
        except OSError:
            continue
    raise RuntimeError("No writable app directory found.")


APP_DIR = resolve_app_dir()
CONFIG_FILE = APP_DIR / "receiver_config.json"
DB_FILE = APP_DIR / "security_suite.db"
LOG_FILE = APP_DIR / "sys_integrity.log"
EVIDENCE_DIR = APP_DIR / "evidence"

DEFAULT_CONFIG = {
    "secondary_email": "",
    "smtp_email": "",
    "tunnel_url": "",
    "listen_port": 8080,
    "bind_host": "127.0.0.1",
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 465,
    "smtp_tls_mode": "ssl",
    "smtp_username": "",
    "smtp_from": "",
    "beacon_secret": "",
    "require_signature": False,
    "rate_limit_window_sec": 60,
    "rate_limit_max_per_ip": 30,
    "dedupe_window_sec": 120,
    "retention_days": 30,
    "max_evidence_files": 5000,
}

RATE_LOCK = threading.Lock()
REQUEST_HISTORY = defaultdict(deque)
RECENT_ALERT_KEYS = {}


def ensure_app_dir() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)


def as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def as_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load_receiver_config():
    ensure_app_dir()
    cfg = DEFAULT_CONFIG.copy()

    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                cfg.update(data)
        except Exception as exc:
            print(f"[CONFIG ERROR] {exc}")

    cfg["secondary_email"] = os.environ.get("GPSD_SECONDARY_EMAIL", cfg.get("secondary_email", ""))
    cfg["smtp_email"] = os.environ.get("GPSD_SMTP_EMAIL", cfg.get("smtp_email", ""))
    cfg["tunnel_url"] = os.environ.get("GPSD_TUNNEL_URL", cfg.get("tunnel_url", ""))
    cfg["bind_host"] = os.environ.get("GPSD_BIND_HOST", cfg.get("bind_host", "127.0.0.1"))

    cfg["listen_port"] = as_int(os.environ.get("GPSD_LISTEN_PORT", cfg.get("listen_port", 8080)), 8080)
    cfg["smtp_host"] = os.environ.get("GPSD_SMTP_HOST", cfg.get("smtp_host", "smtp.gmail.com"))
    cfg["smtp_port"] = as_int(os.environ.get("GPSD_SMTP_PORT", cfg.get("smtp_port", 465)), 465)
    cfg["smtp_tls_mode"] = os.environ.get("GPSD_SMTP_TLS_MODE", cfg.get("smtp_tls_mode", "ssl")).lower().strip()
    cfg["smtp_username"] = os.environ.get("GPSD_SMTP_USERNAME", cfg.get("smtp_username", ""))
    cfg["smtp_from"] = os.environ.get("GPSD_SMTP_FROM", cfg.get("smtp_from", ""))

    cfg["beacon_secret"] = os.environ.get("GPSD_BEACON_SECRET", cfg.get("beacon_secret", ""))
    cfg["require_signature"] = as_bool(os.environ.get("GPSD_REQUIRE_SIGNATURE", cfg.get("require_signature", False)), False)
    cfg["rate_limit_window_sec"] = as_int(os.environ.get("GPSD_RATE_LIMIT_WINDOW_SEC", cfg.get("rate_limit_window_sec", 60)), 60)
    cfg["rate_limit_max_per_ip"] = as_int(os.environ.get("GPSD_RATE_LIMIT_MAX_PER_IP", cfg.get("rate_limit_max_per_ip", 30)), 30)
    cfg["dedupe_window_sec"] = as_int(os.environ.get("GPSD_DEDUPE_WINDOW_SEC", cfg.get("dedupe_window_sec", 120)), 120)
    cfg["retention_days"] = as_int(os.environ.get("GPSD_RETENTION_DAYS", cfg.get("retention_days", 30)), 30)
    cfg["max_evidence_files"] = as_int(os.environ.get("GPSD_MAX_EVIDENCE_FILES", cfg.get("max_evidence_files", 5000)), 5000)

    if not cfg["smtp_username"]:
        cfg["smtp_username"] = cfg.get("smtp_email", "")
    if not cfg["smtp_from"]:
        cfg["smtp_from"] = cfg.get("smtp_email", "")

    app_password = os.environ.get("GPSD_SMTP_PASSWORD", os.environ.get("GPSD_APP_PASSWORD", ""))

    return cfg, app_password


def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS alerts
           (id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT,
            timestamp TEXT,
            received_at_utc TEXT,
            attacker_ip TEXT,
            user_agent TEXT,
            decoy_name TEXT,
            location_data TEXT,
            subject TEXT,
            request_path TEXT,
            x_forwarded_for TEXT,
            cf_connecting_ip TEXT,
            cf_ray TEXT,
            cf_ip_country TEXT,
            latitude REAL,
            longitude REAL)"""
    )
    cursor.execute("PRAGMA table_info(alerts)")
    existing_columns = {row[1] for row in cursor.fetchall()}
    for column, ddl in (
        ("event_id", "ALTER TABLE alerts ADD COLUMN event_id TEXT"),
        ("received_at_utc", "ALTER TABLE alerts ADD COLUMN received_at_utc TEXT"),
        ("request_path", "ALTER TABLE alerts ADD COLUMN request_path TEXT"),
        ("x_forwarded_for", "ALTER TABLE alerts ADD COLUMN x_forwarded_for TEXT"),
        ("cf_connecting_ip", "ALTER TABLE alerts ADD COLUMN cf_connecting_ip TEXT"),
        ("cf_ray", "ALTER TABLE alerts ADD COLUMN cf_ray TEXT"),
        ("cf_ip_country", "ALTER TABLE alerts ADD COLUMN cf_ip_country TEXT"),
        ("latitude", "ALTER TABLE alerts ADD COLUMN latitude REAL"),
        ("longitude", "ALTER TABLE alerts ADD COLUMN longitude REAL"),
    ):
        if column not in existing_columns:
            cursor.execute(ddl)
    conn.commit()
    conn.close()


def write_evidence_file(event):
    ensure_app_dir()
    safe_event_id = str(event.get("event_id", "unknown")).replace("/", "_")
    out_file = EVIDENCE_DIR / f"{safe_event_id}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(event, f, indent=2, ensure_ascii=False)
    return out_file


def prune_old_data(retention_days: int, max_evidence_files: int):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM alerts WHERE received_at_utc IS NOT NULL AND julianday('now') - julianday(received_at_utc) > ?",
            (retention_days,),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"[PRUNE DB ERROR] {exc}")

    try:
        files = sorted(EVIDENCE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)
        cutoff = time.time() - (retention_days * 86400)
        for path in files:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
        files = sorted(EVIDENCE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)
        if len(files) > max_evidence_files:
            for path in files[: len(files) - max_evidence_files]:
                path.unlink(missing_ok=True)
    except Exception as exc:
        print(f"[PRUNE FILE ERROR] {exc}")


def verify_signature(secret: str, src: str, subj: str, ts: str, sig: str) -> bool:
    if not secret:
        return False
    msg = f"{src}|{subj}|{ts}".encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig or "")


def rate_limit_allowed(ip: str, window_sec: int, max_requests: int) -> bool:
    now = time.time()
    with RATE_LOCK:
        dq = REQUEST_HISTORY[ip]
        while dq and now - dq[0] > window_sec:
            dq.popleft()
        if len(dq) >= max_requests:
            return False
        dq.append(now)
        return True


def dedupe_allowed(key: str, dedupe_window_sec: int) -> bool:
    now = time.time()
    with RATE_LOCK:
        stale_keys = [k for k, t in RECENT_ALERT_KEYS.items() if now - t > dedupe_window_sec]
        for stale in stale_keys:
            RECENT_ALERT_KEYS.pop(stale, None)
        last_seen = RECENT_ALERT_KEYS.get(key)
        if last_seen is not None and now - last_seen <= dedupe_window_sec:
            return False
        RECENT_ALERT_KEYS[key] = now
        return True


def is_trusted_forwarder(remote_ip: str) -> bool:
    return remote_ip in {"127.0.0.1", "::1"}


def safe_geo_lookup(ip: str):
    geo_data = "Unknown"
    latitude = None
    longitude = None
    try:
        geo_resp = requests.get(f"https://ipapi.co/{ip}/json/", timeout=5).json()
        geo_data = (
            f"{geo_resp.get('city', '')}, {geo_resp.get('region', '')}, "
            f"{geo_resp.get('country_name', '')} (Org: {geo_resp.get('org', '')})"
        )
        latitude = geo_resp.get("latitude")
        longitude = geo_resp.get("longitude")
    except Exception:
        pass
    return geo_data, latitude, longitude


CONFIG, APP_PASSWORD = load_receiver_config()
YOUR_SECONDARY_EMAIL = CONFIG.get("secondary_email", "")
TUNNEL_URL = CONFIG.get("tunnel_url", "")
LISTEN_PORT = CONFIG.get("listen_port", 8080)
BIND_HOST = CONFIG.get("bind_host", "127.0.0.1")
SMTP_HOST = CONFIG.get("smtp_host", "smtp.gmail.com")
SMTP_PORT = CONFIG.get("smtp_port", 465)
SMTP_TLS_MODE = CONFIG.get("smtp_tls_mode", "ssl")
SMTP_USERNAME = CONFIG.get("smtp_username", "")
SMTP_FROM = CONFIG.get("smtp_from", "")
BEACON_SECRET = CONFIG.get("beacon_secret", "")
REQUIRE_SIGNATURE = bool(CONFIG.get("require_signature", False))
RATE_LIMIT_WINDOW_SEC = int(CONFIG.get("rate_limit_window_sec", 60))
RATE_LIMIT_MAX_PER_IP = int(CONFIG.get("rate_limit_max_per_ip", 30))
DEDUPE_WINDOW_SEC = int(CONFIG.get("dedupe_window_sec", 120))
RETENTION_DAYS = int(CONFIG.get("retention_days", 30))
MAX_EVIDENCE_FILES = int(CONFIG.get("max_evidence_files", 5000))

init_db()
prune_old_data(RETENTION_DAYS, MAX_EVIDENCE_FILES)


class BeaconHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        remote_ip = self.client_address[0]

        if not rate_limit_allowed(remote_ip, RATE_LIMIT_WINDOW_SEC, RATE_LIMIT_MAX_PER_IP):
            self.send_response(429)
            self.end_headers()
            return

        event_id = str(uuid4())
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        src = params.get("src", ["unknown"])[0]
        subj = params.get("subj", ["no_subject"])[0]
        ts = params.get("ts", [datetime.now(timezone.utc).isoformat()])[0]
        sig = params.get("sig", [""])[0]

        signature_required = bool(BEACON_SECRET) or REQUIRE_SIGNATURE
        signature_valid = verify_signature(BEACON_SECRET, src, subj, ts, sig) if signature_required else True

        if signature_required and not signature_valid:
            self.send_response(403)
            self.end_headers()
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now(timezone.utc).isoformat()}] [CID:401] Invalid signature from {remote_ip} src={src} subj={subj}\n")
            return

        ua = self.headers.get("User-Agent", "unknown")
        request_path = self.path

        trusted_forwarder = is_trusted_forwarder(remote_ip)
        x_forwarded_for = self.headers.get("X-Forwarded-For", "") if trusted_forwarder else ""
        cf_connecting_ip = self.headers.get("CF-Connecting-IP", "") if trusted_forwarder else ""
        cf_ray = self.headers.get("CF-Ray", "") if trusted_forwarder else ""
        cf_ip_country = self.headers.get("CF-IPCountry", "") if trusted_forwarder else ""

        attacker_ip = cf_connecting_ip or remote_ip

        dedupe_key = f"{attacker_ip}|{src}|{subj}"
        if not dedupe_allowed(dedupe_key, DEDUPE_WINDOW_SEC):
            self.send_response(202)
            self.end_headers()
            return

        geo_data, latitude, longitude = safe_geo_lookup(attacker_ip)

        received_at_utc = datetime.now(timezone.utc).isoformat()

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO alerts (event_id, timestamp, received_at_utc, attacker_ip, user_agent, decoy_name, location_data, subject, request_path, x_forwarded_for, cf_connecting_ip, cf_ray, cf_ip_country, latitude, longitude) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                event_id,
                ts,
                received_at_utc,
                attacker_ip,
                ua,
                src,
                geo_data,
                subj,
                request_path,
                x_forwarded_for,
                cf_connecting_ip,
                cf_ray,
                cf_ip_country,
                latitude,
                longitude,
            ),
        )
        alert_id = cursor.lastrowid
        conn.commit()
        conn.close()

        lat_lon_text = (
            f"lat={latitude}, lon={longitude}"
            if latitude is not None and longitude is not None
            else "lat/lon=unknown"
        )
        log_entry = (
            f"[ALERT] event={event_id} db_id={alert_id} src={src} subj={subj} "
            f"from={attacker_ip} geo={geo_data} [{lat_lon_text}] cf_ray={cf_ray or 'n/a'} at={ts}"
        )
        print(log_entry)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now(timezone.utc).isoformat()}] {log_entry}\n")

        event_payload = {
            "event_id": event_id,
            "db_id": alert_id,
            "timestamp": ts,
            "received_at_utc": received_at_utc,
            "attacker_ip": attacker_ip,
            "user_agent": ua,
            "decoy_name": src,
            "subject": subj,
            "request_path": request_path,
            "x_forwarded_for": x_forwarded_for,
            "cf_connecting_ip": cf_connecting_ip,
            "cf_ray": cf_ray,
            "cf_ip_country": cf_ip_country,
            "trusted_forwarder": trusted_forwarder,
            "signature_required": signature_required,
            "signature_valid": signature_valid,
            "location_data": geo_data,
            "latitude": latitude,
            "longitude": longitude,
        }
        evidence_file = write_evidence_file(event_payload)
        print(f"[EVIDENCE] {evidence_file}")

        health_like = "healthcheck" in src.lower() or "healthcheck" in subj.lower()
        try:
            if health_like:
                raise RuntimeError("Healthcheck event: email suppressed.")
            if not (SMTP_HOST and SMTP_PORT and SMTP_USERNAME and SMTP_FROM and YOUR_SECONDARY_EMAIL and APP_PASSWORD):
                raise RuntimeError("Set SMTP config/env (host/port/tls/user/from/to/password) to enable email alerts.")

            msg = EmailMessage()
            msg.set_content(f"GPS-DEFENSE BREACH ALERT\n\n{log_entry}\n\nFull report in database: {DB_FILE}\nEvidence: {evidence_file}")
            msg["Subject"] = "!! ACCOUNT COMPROMISE DETECTED !!"
            msg["From"] = SMTP_FROM
            msg["To"] = YOUR_SECONDARY_EMAIL

            if SMTP_TLS_MODE == "ssl":
                with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15) as smtp:
                    smtp.login(SMTP_USERNAME, APP_PASSWORD)
                    smtp.send_message(msg)
            elif SMTP_TLS_MODE == "starttls":
                with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as smtp:
                    smtp.ehlo()
                    smtp.starttls()
                    smtp.ehlo()
                    smtp.login(SMTP_USERNAME, APP_PASSWORD)
                    smtp.send_message(msg)
            else:
                with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as smtp:
                    smtp.login(SMTP_USERNAME, APP_PASSWORD)
                    smtp.send_message(msg)
            print("[EMAIL SENT]")
        except Exception as e:
            print(f"[EMAIL INFO] {e}")

        self.send_response(200)
        self.end_headers()


def run_listener():
    server = HTTPServer((BIND_HOST, LISTEN_PORT), BeaconHandler)
    print(f"[+] Beacon listener active on {BIND_HOST}:{LISTEN_PORT}...")
    if TUNNEL_URL:
        print(f"[+] Expected tunnel endpoint: {TUNNEL_URL}")
    print(f"[+] Signature required: {bool(BEACON_SECRET) or REQUIRE_SIGNATURE}")
    server.serve_forever()


if __name__ == "__main__":
    run_listener()
