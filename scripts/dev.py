"""Start the PRISM backend (FastAPI on :8100) and frontend (Vite on :5174) together.

    python scripts/dev.py            # both
    python scripts/dev.py --backend  # API only
    python scripts/dev.py --prod     # build the frontend, serve everything from FastAPI on :8100
Ctrl+C stops both.
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NPM = shutil.which("npm.cmd") or shutil.which("npm") or "npm"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", action="store_true")
    ap.add_argument("--prod", action="store_true")
    a = ap.parse_args()
    if a.prod:
        subprocess.check_call([NPM, "run", "build"], cwd=ROOT / "frontend")
    api = [sys.executable, "-m", "uvicorn", "api.main:app", "--app-dir", str(ROOT / "backend"),
           "--host", "127.0.0.1", "--port", "8100"] + ([] if a.prod else ["--reload", "--reload-dir", str(ROOT / "backend")])
    procs = [subprocess.Popen(api, cwd=ROOT)]
    if not (a.backend or a.prod):
        procs.append(subprocess.Popen([NPM, "run", "dev", "--", "--host", "127.0.0.1"], cwd=ROOT / "frontend"))
    print("\nPRISM is starting:  frontend http://127.0.0.1:5174   API http://127.0.0.1:8100/docs"
          if not (a.backend or a.prod) else "\nPRISM API: http://127.0.0.1:8100")
    try:
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()


if __name__ == "__main__":
    main()
