import os
from pathlib import Path


def pick_writable_test_dir() -> Path:
    userprofile = os.environ.get("USERPROFILE", str(Path.home()))
    preferred = Path(userprofile) / "OneDrive" / "Sync_Verify_TEST"
    fallback = Path(__file__).resolve().parent / "Sync_Verify_TEST"

    for candidate in (preferred, fallback):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write_probe"
            with open(probe, "w", encoding="utf-8") as f:
                f.write("ok")
            probe.unlink(missing_ok=True)
            return candidate
        except OSError:
            continue

    raise RuntimeError("No writable test directory found.")


path = pick_writable_test_dir()
target = path / "test.html"
with open(target, "w", encoding="utf-8") as f:
    f.write("<h1>Test decoy</h1>")

print(f"Created in: {path}")
