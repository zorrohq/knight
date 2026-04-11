from celery import Celery

from knight.runtime.logging_config import setup_logging
from knight.worker.config import settings


def create_celery_app() -> Celery:
    setup_logging()
    app = Celery(
        settings.celery_app_name,
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
        include=["knight.worker.tasks.run_agent_task"],
    )

    app.conf.update(
        task_default_queue=settings.celery_task_default_queue,
        task_serializer=settings.celery_task_serializer,
        result_serializer=settings.celery_result_serializer,
        accept_content=settings.celery_accept_content,
        timezone=settings.celery_timezone,
        task_track_started=True,
    )
    return app


celery_app = create_celery_app()
