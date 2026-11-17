"""Train or launch the local Rasa insurance assistant."""

import argparse
import logging
import os
import secrets
import subprocess
import sys
import threading
from pathlib import Path
from time import monotonic, sleep

ROOT = Path(__file__).resolve().parent
MODEL = ROOT / "models" / "insurance-rasa.tar.gz"


def cpu_environment() -> dict:
    return {
        **os.environ, "RASA_TELEMETRY_ENABLED": "false", "CUDA_VISIBLE_DEVICES": "-1",
        "TF_CPP_MIN_LOG_LEVEL": "2", "TF_NUM_INTRAOP_THREADS": "2",
        "TF_NUM_INTEROP_THREADS": "2", "OMP_NUM_THREADS": "2",
        "OPENBLAS_NUM_THREADS": "2",
    }


def train():
    subprocess.run(
        [sys.executable, "-m", "rasa", "train", "--config", "rasa/config.yml",
         "--domain", "rasa/domain.yml", "--data", "rasa/data", "--out", "models",
         "--fixed-model-name", "insurance-rasa", "--force"],
        cwd=ROOT, env=cpu_environment(), check=True,
    )


def serve(port: int, rasa_port: int, database: Path):
    from werkzeug.serving import make_server

    from insurance.web import create_app, rasa_request

    if not MODEL.is_file():
        raise SystemExit("Model archive missing. Run: python run.py --train")
    if port == rasa_port:
        raise SystemExit("The web and Rasa ports must be different.")
    token = secrets.token_urlsafe(32)
    env = {**cpu_environment(), "INSURANCE_WEB_PORT": str(port),
           "INSURANCE_ACTION_TOKEN": token, "SANIC_WORKERS": "1"}
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app = create_app(database, rasa_port, token)
    server = make_server("127.0.0.1", port, app, threaded=True)

    log_path = database.parent / "rasa.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "rasa", "run", "--model", str(MODEL),
             "--credentials", "rasa/credentials.yml", "--endpoints", "rasa/endpoints.yml",
             "--interface", "127.0.0.1", "--port", str(rasa_port)],
            cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            print("Loading Rasa Open Source 3.6.21 model…", flush=True)
            deadline = monotonic() + 90
            while monotonic() < deadline and process.poll() is None:
                try:
                    rasa_request(rasa_port, "/")
                    break
                except OSError:
                    sleep(0.25)
            else:
                raise SystemExit(f"Rasa did not start. Read {log_path}")

            def watch_rasa():
                process.wait()
                server.shutdown()

            threading.Thread(target=watch_rasa, daemon=True).start()
            print(f"Insurance Assistant ready at http://127.0.0.1:{port}", flush=True)
            print("Use the sample policies and the on-screen demo inbox. Ctrl+C stops both services.",
                  flush=True)
            server.serve_forever()
            if process.poll() is not None:
                raise SystemExit(f"Rasa stopped unexpectedly. Read {log_path}")
        except KeyboardInterrupt:
            print("\nStopped.", flush=True)
        finally:
            server.server_close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def main():
    if sys.version_info[:2] != (3, 10):
        raise SystemExit("Use 64-bit Python 3.10 for this Rasa release. See README.md.")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", action="store_true", help="Retrain the supplied Rasa model")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--rasa-port", type=int, default=5005)
    parser.add_argument("--db", type=Path, default=ROOT / "instance" / "insurance.sqlite3")
    args = parser.parse_args()
    if args.train:
        train()
    else:
        serve(args.port, args.rasa_port, args.db.resolve())


if __name__ == "__main__":
    main()
