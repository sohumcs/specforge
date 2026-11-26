"""Seed / reset the demo sandbox:  python -m app.seed

Creates the demo user + Sandbox project if needed, removes every sandbox
blueprint, restores the four curated samples and verifies them (loads the ML
models, so run it where the worker runs). Used by `make seed`, the k8s seed
Job, and the nightly Celery beat task.
"""

import json

from app.core.logging import configure_logging
from app.db.session import SessionLocal, get_engine
from app.services.samples import reset_sandbox


def main() -> None:
    configure_logging()
    get_engine()
    with SessionLocal() as db:
        print(json.dumps(reset_sandbox(db), indent=1))


if __name__ == "__main__":
    main()
