"""Celery application.

Reliability settings and why:
* acks_late + reject_on_worker_lost - a task is acknowledged only after it
  finishes, so if the worker pod dies mid-job Redis redelivers it.
* visibility_timeout > hard time limit - Redis won't redeliver a task that is
  still legitimately running.
* prefetch_multiplier=1 - long jobs aren't hoarded by one busy worker.
* ignore_result - job state/results live in Postgres, not a result backend.

Pool: run the worker with `-P threads -c 2`. Threads share ONE copy of the
spaCy / sentence-transformer / NLI models (hundreds of MB), which matters on a
12 GB free VM. Inference releases the GIL, so threads still overlap.
"""

import logging

from celery import Celery
from celery.signals import worker_init

from app.core.config import get_settings
from app.core.logging import configure_logging

s = get_settings()

celery_app = Celery("specforge", broker=s.redis_url, include=["app.worker.tasks"])
celery_app.conf.update(
    task_default_queue="specforge",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_ignore_result=True,
    task_soft_time_limit=s.celery_task_soft_limit,
    task_time_limit=s.celery_task_hard_limit,
    worker_prefetch_multiplier=1,
    worker_hijack_root_logger=False,
    broker_connection_retry_on_startup=True,
    broker_connection_timeout=3,
    broker_transport_options={"visibility_timeout": s.celery_task_hard_limit * 2},
    task_always_eager=s.celery_eager,
    beat_schedule={},  # populated in Phase 6 (nightly sandbox reset)
)


@worker_init.connect
def _warm_up(**_: object) -> None:
    """Load models once per worker process before the first job arrives, and
    expose Prometheus metrics for the worker on :9100."""
    configure_logging(s.log_level)
    log = logging.getLogger("specforge.worker")
    from prometheus_client import start_http_server

    from app.nlp.brief import get_nlp

    get_nlp()
    try:
        start_http_server(9100)
    except OSError:
        log.warning("metrics port 9100 busy; worker metrics disabled")
    log.info("worker warmed up (spaCy loaded)")
