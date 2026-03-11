import customtkinter as ctk
import hashlib
import hmac
import json
import os
import socket
import subprocess
import sys
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import messagebox as mb
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from randomizers import random_bait_subject, random_decoy_filename

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

PALETTE = {
    "bg": "#0B1320",
    "surface": "#111A2B",
    "surface_alt": "#17243A",
    "accent": "#2FD6A8",
    "accent_hover": "#24B48D",
    "text": "#EAF2FF",
    "muted": "#9CB0CF",
    "warning": "#F2B84B",
}

RECEIVER_TEMPLATE_BASENAME = "receiver_config.template.json"


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
CONFIG_FILE = APP_DIR / "config.json"
LOG_FILE = APP_DIR / "sys_integrity.log"
RECEIVER_RUN_LOG = APP_DIR / "receiver_run.log"
TUNNEL_RUN_LOG = APP_DIR / "tunnel_run.log"
DEFAULT_CONFIG = {
    "beacon_url": "https://defense.01ai.ai/log",
    "tunnel_name": "01ai_defense",
    "beacon_secret": "",
    "custom_filename_prefix": "",
}


def ensure_app_dir() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)


def ensure_receiver_template() -> Path:
    ensure_app_dir()
    template_path = APP_DIR / RECEIVER_TEMPLATE_BASENAME
    if template_path.exists():
        return template_path

    template = {
        "secondary_email": "alerts@yourdomain.com",
        "smtp_email": "alerts@yourdomain.com",
        "smtp_host": "smtp.yourprovider.com",
        "smtp_port": 587,
        "smtp_tls_mode": "starttls",
        "smtp_username": "alerts@yourdomain.com",
        "smtp_from": "alerts@yourdomain.com",
        "tunnel_url": "https://your-tunnel.example.com/log",
        "listen_port": 8080,
        "notes": "Password is not stored here. Set GPSD_SMTP_PASSWORD env var before starting beacon_receiver.py",
    }
    with open(template_path, "w", encoding="utf-8") as f:
        json.dump(template, f, indent=4)

    return template_path


def load_config():
    ensure_app_dir()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = DEFAULT_CONFIG.copy()
            if isinstance(data, dict):
                merged.update(data)
            return merged
        except Exception:
            return DEFAULT_CONFIG.copy()
    return DEFAULT_CONFIG.copy()


def save_config(config):
    ensure_app_dir()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)


def log_telemetry(status_code, detail):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ensure_app_dir()
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [CID:{status_code}] {detail}\n")
    except Exception as e:
        print(f"Logging error: {e}")


def build_beacon_url(beacon_url: str, src: str, subj: str, ts: str, secret: str = "") -> str:
    secret = (secret or "").strip()
    parts = urlsplit(beacon_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({"src": src, "subj": subj, "ts": ts})
    if secret:
        msg = f"{src}|{subj}|{ts}".encode("utf-8")
        query["sig"] = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def discover_sync_roots(user_profile: str):
    profile = Path(user_profile)
    roots = []
    common_paths = [
        profile / "OneDrive",
        profile / "OneDrive - Personal",
        profile / "Google Drive",
        profile / "Google Drive - My Drive",
    ]

    for p in common_paths:
        if p.exists() and p.is_dir():
            roots.append(p)

    for pattern in ("OneDrive*", "Google Drive*"):
        for p in profile.glob(pattern):
            if p.exists() and p.is_dir():
                roots.append(p)

    seen = set()
    unique_roots = []
    for root in roots:
        key = str(root).lower()
        if key not in seen:
            seen.add(key)
            unique_roots.append(root)

    one_roots = [p for p in unique_roots if p.name.lower().startswith("onedrive")]
    gdrive_roots = [p for p in unique_roots if p.name.lower().startswith("google drive")]
    return one_roots, gdrive_roots


def deploy_decoys_to_path(path, account_type, username, beacon_url, custom_prefix="", beacon_secret=""):
    target_dir = Path(path)
    if not target_dir.exists():
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            log_telemetry(100, f"Created folder: {target_dir}")
        except Exception as e:
            log_telemetry(102, f"Failed to create {target_dir}: {e}")
            return False

    custom_prefix = str(custom_prefix).strip()
    html_name = random_decoy_filename(account_type, "html")
    pdf_name = random_decoy_filename(account_type, "pdf")
    if custom_prefix:
        html_name = f"{custom_prefix}{html_name}"
        pdf_name = f"{custom_prefix}{pdf_name}"
    subj = random_bait_subject(account_type, username)

    html_path = target_dir / html_name
    beacon_src = build_beacon_url(beacon_url, html_name, subj, datetime.now().isoformat(), secret=beacon_secret)
    html_content = f"""
    <!DOCTYPE html>
    <html><head><title>Confidential Backup</title></head>
    <body>
    <h2>{subj}</h2>
    <p>Do not share. Last updated: {datetime.now().strftime('%B %Y')}</p>
    <pre>Seed: word1 word2 ... word12</pre>
    <img src=\"{beacon_src}\" style=\"display:none;\" width=\"1\" height=\"1\">
    </body></html>
    """
    try:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        log_telemetry(101, f"Created HTML decoy: {html_name} in {target_dir}")
    except Exception as e:
        log_telemetry(103, f"Failed HTML in {target_dir}: {e}")

    pdf_path = target_dir / pdf_name
    try:
        with open(pdf_path, "w", encoding="utf-8") as f:
            f.write("%PDF-1.4\n% Verification Active\n")
        log_telemetry(101, f"Created PDF decoy: {pdf_name} in {target_dir}")
    except Exception as e:
        log_telemetry(103, f"Failed PDF in {target_dir}: {e}")

    return True


class AISVApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Cloud Sync Decoy Monitor")
        self.root.geometry("760x620")
        self.root.minsize(700, 560)
        self.root.configure(fg_color=PALETTE["bg"])

        self.config = load_config()
        self.receiver_template_path = ensure_receiver_template()
        self.account_type = "General"
        self.username = self.default_username()
        self.setup_complete = False
        self.receiver_proc = None
        self.tunnel_proc = None
        self.root.protocol("WM_DELETE_WINDOW", self.on_app_close)

        shell = ctk.CTkFrame(root, fg_color="transparent")
        shell.pack(fill="both", expand=True, padx=18, pady=18)

        hero = ctk.CTkFrame(shell, corner_radius=14, fg_color=PALETTE["surface"])
        hero.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            hero,
            text="Cloud Sync Decoy Monitor",
            font=("Bahnschrift SemiBold", 28),
            text_color=PALETTE["text"],
        ).pack(anchor="w", padx=18, pady=(14, 0))
        ctk.CTkLabel(
            hero,
            text="Asset Integrity and Sync Verification",
            font=("Bahnschrift", 14),
            text_color=PALETTE["muted"],
        ).pack(anchor="w", padx=18, pady=(2, 14))

        body = ctk.CTkFrame(shell, corner_radius=14, fg_color=PALETTE["surface_alt"])
        body.pack(fill="both", expand=True)

        self.status_badge = ctk.CTkLabel(
            body,
            text="Status: Setup required",
            font=("Bahnschrift", 13, "bold"),
            text_color=PALETTE["warning"],
        )
        self.status_badge.pack(anchor="w", padx=18, pady=(16, 8))

        ctk.CTkLabel(
            body,
            text="Deploy decoys into synced folders and track beacon callbacks.",
            font=("Bahnschrift", 13),
            text_color=PALETTE["muted"],
        ).pack(anchor="w", padx=18, pady=(0, 10))

        ctk.CTkLabel(
            body,
            text="Receiver also needs SMTP settings (host, port, tls mode, user, from, to, password).",
            font=("Bahnschrift", 12),
            text_color=PALETTE["muted"],
        ).pack(anchor="w", padx=18, pady=(0, 14))

        self.advanced_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            body,
            text="Enable Advanced Mode",
            variable=self.advanced_var,
            checkbox_width=18,
            checkbox_height=18,
        ).pack(anchor="w", padx=18, pady=(0, 16))

        ctk.CTkButton(
            body,
            text="Quick Setup (Recommended)",
            command=self.quick_setup,
            corner_radius=10,
            height=42,
            fg_color=PALETTE["accent"],
            hover_color=PALETTE["accent_hover"],
            text_color="#04110E",
            font=("Bahnschrift SemiBold", 14),
        ).pack(fill="x", padx=18, pady=(0, 10))

        ctk.CTkButton(
            body,
            text="Launch Setup Assistant",
            command=self.open_setup_wizard,
            corner_radius=10,
            height=42,
            fg_color="#2A3D5E",
            hover_color="#34507D",
            font=("Bahnschrift SemiBold", 14),
        ).pack(fill="x", padx=18, pady=(0, 10))

        self.start_btn = ctk.CTkButton(
            body,
            text="Start Monitoring",
            command=self.start_service,
            corner_radius=10,
            height=42,
            fg_color="#2A3D5E",
            hover_color="#34507D",
            state="disabled",
            font=("Bahnschrift SemiBold", 14),
        )
        self.start_btn.pack(fill="x", padx=18, pady=(0, 10))

        ctk.CTkButton(
            body,
            text="Start All Services",
            command=self.start_all_services,
            corner_radius=10,
            height=38,
            fg_color="#315F4C",
            hover_color="#3C745C",
            font=("Bahnschrift", 13),
        ).pack(fill="x", padx=18, pady=(0, 10))

        ctk.CTkButton(
            body,
            text="Stop All Services",
            command=self.stop_all_services,
            corner_radius=10,
            height=38,
            fg_color="#6A2E3A",
            hover_color="#7F3745",
            font=("Bahnschrift", 13),
        ).pack(fill="x", padx=18, pady=(0, 10))

        ctk.CTkButton(
            body,
            text="Validate Setup",
            command=self.validate_setup,
            corner_radius=10,
            height=38,
            fg_color="#25385A",
            hover_color="#2F4873",
            font=("Bahnschrift", 13),
        ).pack(fill="x", padx=18, pady=(0, 10))

        ctk.CTkButton(
            body,
            text="Run Sync Path Test",
            command=self.run_sync_path_test,
            corner_radius=10,
            height=38,
            fg_color="#25385A",
            hover_color="#2F4873",
            font=("Bahnschrift", 13),
        ).pack(fill="x", padx=18, pady=(0, 10))

        controls = ctk.CTkFrame(body, fg_color="transparent")
        controls.pack(fill="x", padx=18)
        controls.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkButton(
            controls,
            text="Open Data Folder",
            command=self.open_data_folder,
            corner_radius=10,
            height=36,
            fg_color="#20314F",
            hover_color="#2A3E63",
            font=("Bahnschrift", 13),
        ).grid(row=0, column=0, sticky="ew", padx=(0, 6))

        ctk.CTkButton(
            controls,
            text="Open Receiver Template",
            command=self.open_receiver_template,
            corner_radius=10,
            height=36,
            fg_color="#20314F",
            hover_color="#2A3E63",
            font=("Bahnschrift", 13),
        ).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        ctk.CTkLabel(
            body,
            text=f"Data path: {APP_DIR}",
            font=("Consolas", 11),
            text_color=PALETTE["muted"],
            wraplength=700,
            justify="left",
        ).pack(anchor="w", padx=18, pady=(12, 2))
        ctk.CTkLabel(
            body,
            text=f"Receiver template: {self.receiver_template_path}",
            font=("Consolas", 11),
            text_color=PALETTE["muted"],
            wraplength=700,
            justify="left",
        ).pack(anchor="w", padx=18, pady=(0, 14))

    def open_data_folder(self):
        ensure_app_dir()
        os.startfile(str(APP_DIR))

    def open_receiver_template(self):
        template = ensure_receiver_template()
        os.startfile(str(template))

    def _proc_alive(self, proc):
        return proc is not None and proc.poll() is None

    def _append_run_log(self, run_log_path: Path, title: str):
        with open(run_log_path, "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.now().isoformat()}] {title}\n")
        return open(run_log_path, "a", encoding="utf-8")

    def _start_receiver_process(self):
        if self._proc_alive(self.receiver_proc):
            return "already running"
        script_path = Path(__file__).resolve().parent / "beacon_receiver.py"
        receiver_log = self._append_run_log(RECEIVER_RUN_LOG, "starting beacon_receiver.py")
        env = os.environ.copy()
        beacon_secret = str(self.config.get("beacon_secret", "")).strip()
        if beacon_secret and not env.get("GPSD_BEACON_SECRET"):
            env["GPSD_BEACON_SECRET"] = beacon_secret
            env["GPSD_REQUIRE_SIGNATURE"] = "true"
        self.receiver_proc = subprocess.Popen(
            [sys.executable, str(script_path)],
            cwd=str(Path(__file__).resolve().parent),
            env=env,
            stdout=receiver_log,
            stderr=subprocess.STDOUT,
        )
        return f"started (pid={self.receiver_proc.pid})"

    def _build_tunnel_command(self):
        token = (
            os.environ.get("TUNNEL_TOKEN", "").strip()
            or os.environ.get("GPSD_TUNNEL_TOKEN", "").strip()
            or os.environ.get("CLOUDFLARED_TUNNEL_TOKEN", "").strip()
        )
        if token:
            return ["cloudflared", "tunnel", "run", "--token", token]

        tunnel_name = (self.config.get("tunnel_name") or "01ai_defense").strip()
        return ["cloudflared", "tunnel", "run", tunnel_name]

    def _start_tunnel_process(self):
        if self._proc_alive(self.tunnel_proc):
            return "already running"
        tunnel_log = self._append_run_log(TUNNEL_RUN_LOG, "starting cloudflared tunnel")
        cmd = self._build_tunnel_command()
        self.tunnel_proc = subprocess.Popen(
            cmd,
            cwd=str(Path(__file__).resolve().parent),
            stdout=tunnel_log,
            stderr=subprocess.STDOUT,
        )
        return f"started (pid={self.tunnel_proc.pid})"

    def start_all_services(self):
        receiver_state = self._start_receiver_process()
        try:
            tunnel_state = self._start_tunnel_process()
        except FileNotFoundError:
            tunnel_state = "failed: cloudflared not found in PATH"
        self.status_badge.configure(text="Status: Services started", text_color=PALETTE["accent"])
        mb.showinfo(
            "Services",
            f"Receiver: {receiver_state}\nTunnel: {tunnel_state}\n\n"
            f"Receiver log: {RECEIVER_RUN_LOG}\nTunnel log: {TUNNEL_RUN_LOG}",
        )

    def stop_all_services(self, show_message=True):
        stopped = []
        if self._proc_alive(self.receiver_proc):
            self.receiver_proc.terminate()
            stopped.append("receiver")
        if self._proc_alive(self.tunnel_proc):
            self.tunnel_proc.terminate()
            stopped.append("tunnel")
        self.receiver_proc = None
        self.tunnel_proc = None
        if show_message:
            if stopped:
                self.status_badge.configure(text="Status: Services stopped", text_color=PALETTE["warning"])
                mb.showinfo("Services", f"Stopped: {', '.join(stopped)}")
            else:
                mb.showinfo("Services", "No app-managed service processes were running.")

    def on_app_close(self):
        self.stop_all_services(show_message=False)
        self.root.destroy()

    def default_username(self):
        name = os.environ.get("USERNAME", "user").strip() or "user"
        return f"{name}@local"

    def _can_connect_to_url(self, url):
        try:
            parts = urlsplit(url)
            host = parts.hostname
            if not host:
                return False
            port = parts.port or (443 if parts.scheme == "https" else 80)
            with socket.create_connection((host, port), timeout=2):
                return True
        except OSError:
            return False

    def detect_beacon_url(self):
        candidates = []
        configured = (self.config.get("beacon_url") or "").strip()
        if configured:
            candidates.append(configured)
        candidates.extend(
            [
                "https://defense.01ai.ai/log",
                "http://127.0.0.1:8080/log",
                "http://127.0.0.1:8090/log",
            ]
        )

        seen = set()
        ordered = []
        for candidate in candidates:
            if candidate not in seen:
                seen.add(candidate)
                ordered.append(candidate)

        for candidate in ordered:
            if self._can_connect_to_url(candidate):
                return candidate, True
        return configured or DEFAULT_CONFIG["beacon_url"], False

    def _mark_setup_ready(self):
        self.setup_complete = True
        self.start_btn.configure(state="normal", fg_color=PALETTE["accent"], hover_color=PALETTE["accent_hover"], text_color="#04110E")
        self.status_badge.configure(text="Status: Ready to deploy", text_color=PALETTE["accent"])

    def quick_setup(self):
        self.account_type = self.account_type or "General"
        self.username = self.username or self.default_username()
        if not self.config.get("beacon_secret"):
            env_secret = os.environ.get("GPSD_BEACON_SECRET", "").strip()
            if env_secret:
                self.config["beacon_secret"] = env_secret

        beacon_url, reachable = self.detect_beacon_url()
        self.config["beacon_url"] = beacon_url
        save_config(self.config)
        self._mark_setup_ready()

        user_profile = os.environ.get("USERPROFILE", os.path.expanduser("~"))
        one_roots, gdrive_roots = discover_sync_roots(user_profile)
        sync_count = len(one_roots) + len(gdrive_roots)
        reach_text = "reachable" if reachable else "not reachable yet"

        mb.showinfo(
            "Quick Setup Complete",
            f"Account: {self.account_type}\n"
            f"User: {self.username}\n"
            f"Beacon: {beacon_url} ({reach_text})\n"
            f"Sync roots found: {sync_count}\n\n"
            "You can click Start Monitoring now. Use Validate Setup if you want a full check first.",
        )

    def validate_setup(self):
        beacon_url = (self.config.get("beacon_url") or "").strip()
        beacon_ok = self._can_connect_to_url(beacon_url) if beacon_url else False

        user_profile = os.environ.get("USERPROFILE", os.path.expanduser("~"))
        one_roots, gdrive_roots = discover_sync_roots(user_profile)

        lines = [
            f"Beacon URL: {beacon_url or '(not set)'}",
            f"Beacon reachable: {'yes' if beacon_ok else 'no'}",
            f"OneDrive roots: {len(one_roots)}",
            f"Google Drive roots: {len(gdrive_roots)}",
        ]
        if one_roots:
            lines.extend([f"  - {p}" for p in one_roots])
        if gdrive_roots:
            lines.extend([f"  - {p}" for p in gdrive_roots])

        if beacon_ok and (one_roots or gdrive_roots):
            self._mark_setup_ready()
            title = "Validation Passed"
        else:
            self.status_badge.configure(text="Status: Validation needed", text_color=PALETTE["warning"])
            title = "Validation Incomplete"

        mb.showinfo(title, "\n".join(lines))

    def run_sync_path_test(self):
        user_profile = os.environ.get("USERPROFILE", os.path.expanduser("~"))
        one_roots, gdrive_roots = discover_sync_roots(user_profile)
        all_roots = [("OneDrive", p) for p in one_roots] + [("Google Drive", p) for p in gdrive_roots]

        if not all_roots:
            mb.showwarning(
                "Sync Test",
                "No OneDrive or Google Drive folders were detected under your user profile.\n"
                "Verify desktop sync clients are installed and signed in.",
            )
            return

        results = []
        for provider, root in all_roots:
            test_dir = root / "Sync_Verify_TEST"
            probe_file = test_dir / "_gps_defense_probe.txt"
            try:
                test_dir.mkdir(parents=True, exist_ok=True)
                with open(probe_file, "w", encoding="utf-8") as f:
                    f.write(f"Cloud Sync Decoy Monitor sync probe {datetime.now().isoformat()}\n")
                results.append(f"OK   {provider}: {probe_file}")
            except Exception as exc:
                results.append(f"FAIL {provider}: {test_dir} ({exc})")

        mb.showinfo("Sync Test Results", "\n".join(results))

    def open_setup_wizard(self):
        try:
            wizard = ctk.CTkToplevel(self.root)
            wizard.title("Setup Assistant")
            wizard.geometry("600x560")
            wizard.attributes("-topmost", True)
            wizard.grab_set()
            wizard.configure(fg_color=PALETTE["bg"])

            tabview = ctk.CTkTabview(wizard, fg_color=PALETTE["surface"], segmented_button_fg_color="#243754")
            tabview.pack(pady=18, padx=18, fill="both", expand=True)

            step1 = tabview.add("Account")
            ctk.CTkLabel(step1, text="Choose account type", font=("Bahnschrift", 15, "bold")).pack(pady=(16, 10))
            self.account_combo = ctk.CTkComboBox(step1, values=["Google", "Microsoft", "General"], command=self.set_account_type, width=320)
            self.account_combo.pack(pady=4)
            self.account_combo.set(self.account_type or "General")

            ctk.CTkLabel(step1, text="Username or email", font=("Bahnschrift", 13)).pack(pady=(14, 6))
            self.username_entry = ctk.CTkEntry(step1, width=360, placeholder_text="example@gmail.com")
            self.username_entry.pack(pady=2)
            self.username_entry.insert(0, self.username or self.default_username())

            ctk.CTkButton(step1, text="Continue", command=lambda: tabview.set("Beacon"), width=160).pack(pady=20)

            step2 = tabview.add("Beacon")
            ctk.CTkLabel(step2, text="Set listener endpoint", font=("Bahnschrift", 15, "bold")).pack(pady=(16, 10))
            ctk.CTkLabel(
                step2,
                text="Run your beacon listener and paste the public HTTPS URL.",
                font=("Bahnschrift", 12),
                text_color=PALETTE["muted"],
            ).pack(pady=(0, 10))

            ctk.CTkButton(
                step2,
                text="Open Cloudflare Tunnel Guide",
                command=lambda: webbrowser.open("https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/tunnel-guide/"),
            ).pack(pady=6)

            self.beacon_url_entry = ctk.CTkEntry(step2, width=420, placeholder_text="https://example.trycloudflare.com/log")
            self.beacon_url_entry.insert(0, self.config.get("beacon_url", ""))
            self.beacon_url_entry.pack(pady=10)

            ctk.CTkButton(step2, text="Continue", command=lambda: tabview.set("Receiver"), width=160).pack(pady=14)

            step3 = tabview.add("Receiver")
            ctk.CTkLabel(step3, text="Receiver email settings", font=("Bahnschrift", 15, "bold")).pack(pady=(16, 10))
            ctk.CTkLabel(
                step3,
                text=(
                    "Set these environment variables before running beacon_receiver.py:\n"
                    "GPSD_SMTP_HOST, GPSD_SMTP_PORT, GPSD_SMTP_TLS_MODE, GPSD_SMTP_USERNAME,\n"
                    "GPSD_SMTP_FROM, GPSD_SECONDARY_EMAIL, GPSD_SMTP_PASSWORD"
                ),
                font=("Consolas", 11),
                text_color=PALETTE["muted"],
                justify="left",
            ).pack(pady=(0, 10), padx=10, anchor="w")

            ctk.CTkButton(step3, text="Open Receiver Template", command=self.open_receiver_template, width=200).pack(pady=6)
            ctk.CTkButton(step3, text="Save and Finish", command=self.complete_setup, width=200).pack(pady=12)

            if self.advanced_var.get():
                adv = tabview.add("Advanced")
                ctk.CTkLabel(adv, text="Advanced options", font=("Bahnschrift", 15, "bold")).pack(pady=(16, 10))
                self.custom_prefix = ctk.CTkEntry(adv, width=320, placeholder_text="Custom filename prefix (optional)")
                self.custom_prefix.pack(pady=5)
                self.custom_prefix.insert(0, str(self.config.get("custom_filename_prefix", "")))

                ctk.CTkLabel(adv, text="Beacon signing secret (optional)", font=("Bahnschrift", 12)).pack(pady=(14, 4))
                self.beacon_secret_entry = ctk.CTkEntry(adv, width=320, placeholder_text="Set to require signed beacons", show="*")
                self.beacon_secret_entry.pack(pady=5)
                self.beacon_secret_entry.insert(0, str(self.config.get("beacon_secret", "")))

                ctk.CTkLabel(adv, text="Tunnel name (optional)", font=("Bahnschrift", 12)).pack(pady=(14, 4))
                self.tunnel_name_entry = ctk.CTkEntry(adv, width=320, placeholder_text="e.g. 01ai_defense")
                self.tunnel_name_entry.pack(pady=5)
                self.tunnel_name_entry.insert(0, str(self.config.get("tunnel_name", "01ai_defense")))

        except Exception as e:
            mb.showerror("Setup Error", f"Failed to open wizard:\n{e}")

    def set_account_type(self, choice):
        self.account_type = choice

    def complete_setup(self):
        if hasattr(self, "account_combo"):
            selected = self.account_combo.get().strip()
            if selected:
                self.account_type = selected
        self.username = self.username_entry.get().strip()
        if not self.account_type or not self.username:
            mb.showwarning("Incomplete", "Please select an account type and enter username/email.")
            return

        url = self.beacon_url_entry.get().strip()
        if url and url.startswith("https://"):
            self.config["beacon_url"] = url
            if hasattr(self, "custom_prefix"):
                self.config["custom_filename_prefix"] = self.custom_prefix.get().strip()
            if hasattr(self, "beacon_secret_entry"):
                self.config["beacon_secret"] = self.beacon_secret_entry.get().strip()
            if hasattr(self, "tunnel_name_entry"):
                self.config["tunnel_name"] = self.tunnel_name_entry.get().strip() or "01ai_defense"
            save_config(self.config)
            mb.showinfo("Saved", "Beacon URL saved.")
        elif url:
            mb.showwarning("Invalid URL", "Beacon URL must start with https://")

        self._mark_setup_ready()
        mb.showinfo(
            "Setup Complete",
            "Configuration saved.\n\nRun Sync Path Test to verify where files are created, then click Start Monitoring.",
        )

    def start_service(self):
        if not self.setup_complete:
            mb.showinfo("Reminder", "Run Setup Assistant first.")
            return

        beacon_url = self.config.get("beacon_url", DEFAULT_CONFIG["beacon_url"])
        if beacon_url == DEFAULT_CONFIG["beacon_url"]:
            if not mb.askyesno("Warning", "No custom beacon URL set. Continue with placeholder?"):
                return

        log_telemetry(200, f"Starting service for {self.account_type}:{self.username} | Beacon: {beacon_url}")

        user_profile = os.environ.get("USERPROFILE", os.path.expanduser("~"))
        one_roots, gdrive_roots = discover_sync_roots(user_profile)
        deployed_locations = []
        custom_prefix = str(self.config.get("custom_filename_prefix", "")).strip()
        beacon_secret = os.environ.get("GPSD_BEACON_SECRET", str(self.config.get("beacon_secret", ""))).strip()

        if not one_roots:
            log_telemetry(104, "OneDrive folder not found - skipping")
        for root in one_roots:
            sync_path = root / "Sync_Verify"
            if deploy_decoys_to_path(sync_path, self.account_type, self.username, beacon_url, custom_prefix=custom_prefix, beacon_secret=beacon_secret):
                deployed_locations.append(str(sync_path))

        if not gdrive_roots:
            log_telemetry(105, "Google Drive folder not found - skipping")
        for root in gdrive_roots:
            sync_path = root / "Sync_Verify"
            if deploy_decoys_to_path(sync_path, self.account_type, self.username, beacon_url, custom_prefix=custom_prefix, beacon_secret=beacon_secret):
                deployed_locations.append(str(sync_path))

        log_telemetry(201, "Monitoring active - decoys deployed")
        self.status_badge.configure(text="Status: Monitoring active", text_color=PALETTE["accent"])

        location_text = "\n".join(deployed_locations) if deployed_locations else "No sync folders found"
        mb.showinfo("Cloud Sync Decoys Armed", f"Beacon: {beacon_url}\n\nDecoys deployed to:\n{location_text}")


if __name__ == "__main__":
    root = ctk.CTk()
    app = AISVApp(root)
    root.mainloop()
