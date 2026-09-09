"""Authoritative web entry point: `python -m stcs_web`.

Runs the existing FastAPI application defined in stcs_web.main (no app-logic duplication).
"""
import os

import uvicorn

from stcs_web.main import app


def main() -> None:
    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_PORT", "8000"))
    reload = os.environ.get("WEB_RELOAD", "0") == "1"
    uvicorn.run(app, host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
