"""Low-memory cloud entry point; the original local Rasa launcher remains run.py."""
import os
from pathlib import Path

from werkzeug.serving import make_server

from insurance.web import create_app

ROOT = Path(__file__).resolve().parent


def main():
    port = int(os.environ.get("PORT", "8000"))
    database = Path(os.environ.get("INSURANCE_DB", str(ROOT / "instance" / "insurance.sqlite3")))
    app = create_app(database, lightweight=True)
    server = make_server("0.0.0.0", port, app, threaded=True)
    print(f"Insurance Assistant cloud demo listening on 0.0.0.0:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
