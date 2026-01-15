"""Celery application configuration."""

import os
from celery import Celery
from celery.schedules import crontab

# Get Redis URLs from environment
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")

# Create Celery app
celery_app = Celery(
    "netsentinel",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=[
        "app.workers.aggregation",
        "app.workers.scoring",
        "app.workers.alerting",
    ]
)

# Celery configuration
celery_app.conf.update(
    # Task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,

    # Task execution settings
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,

    # Result settings
    result_expires=3600,  # 1 hour

    # Beat schedule for periodic tasks
    beat_schedule={
        # Run aggregation every 5 minutes
        "aggregate-flows-5min": {
            "task": "app.workers.aggregation.aggregate_flows",
            "schedule": crontab(minute="*/5"),
            "args": (),
        },
        # Run ML scoring after aggregation (offset by 1 minute)
        "score-anomalies": {
            "task": "app.workers.scoring.score_anomalies",
            "schedule": crontab(minute="1,6,11,16,21,26,31,36,41,46,51,56"),
            "args": (),
        },
        # Generate alerts from scores
        "generate-alerts": {
            "task": "app.workers.alerting.generate_alerts",
            "schedule": crontab(minute="2,7,12,17,22,27,32,37,42,47,52,57"),
            "args": (),
        },
    },
)
