import shutil
import time
from pathlib import Path

from celery import Celery
from celery.signals import worker_ready
from kombu import Queue

from knight.runtime.logging_config import get_logger, setup_logging
from knight.worker.config import settings

logger = get_logger(__name__)

# Worktrees untouched for longer than this are considered orphaned.
_STALE_WORKTREE_AGE_SECONDS = 60 * 60 * 4  # 4 hours

_MAIN_QUEUE = settings.celery_task_default_queue
_DLQ_QUEUE = f"{_MAIN_QUEUE}-dlq"


def create_celery_app() -> Celery:
    setup_logging()
    app = Celery(
        settings.celery_app_name,
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
        include=[
            "knight.worker.tasks.run_agent_task",
            "knight.worker.tasks.dlq_task",
        ],
    )

    app.conf.update(
        task_default_queue=_MAIN_QUEUE,
        task_queues=[
            Queue(_MAIN_QUEUE),
            Queue(_DLQ_QUEUE),
        ],
        task_serializer=settings.celery_task_serializer,
        result_serializer=settings.celery_result_serializer,
        accept_content=settings.celery_accept_content,
        timezone=settings.celery_timezone,
        task_track_started=True,
    )
    return app


@worker_ready.connect
def _cleanup_stale_worktrees(sender: object, **kwargs: object) -> None:
    """Remove worktree directories that were left behind by crashed tasks."""
    sandboxes_root = Path(settings.worker_sandbox_root)
    if not sandboxes_root.is_dir():
        return
    cutoff = time.time() - _STALE_WORKTREE_AGE_SECONDS
    removed = 0
    for worktrees_dir in sandboxes_root.glob("*/worktrees"):
        for candidate in worktrees_dir.iterdir():
            if not candidate.is_dir():
                continue
            try:
                if candidate.stat().st_mtime < cutoff:
                    shutil.rmtree(candidate, ignore_errors=True)
                    removed += 1
                    logger.info("cleaned up stale worktree: %s", candidate)
            except OSError:
                pass
    if removed:
        logger.info("startup cleanup: removed %d stale worktree(s)", removed)


celery_app = create_celery_app()
