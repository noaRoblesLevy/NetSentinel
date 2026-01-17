"""
Celery application configuration with reliability features.

Features:
- Automatic retries with exponential backoff
- Task time limits to prevent runaway tasks
- Late acknowledgment for at-least-once processing
- Structured logging for task monitoring
"""

import logging
import os
from celery import Celery, signals
from celery.schedules import crontab
from datetime import datetime

logger = logging.getLogger(__name__)

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
    # Task serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,

    # Reliability settings
    task_acks_late=True,  # Acknowledge only after task completes
    task_reject_on_worker_lost=True,  # Re-queue if worker dies
    worker_prefetch_multiplier=1,  # Fetch one task at a time

    # Task time limits (soft/hard in seconds)
    task_soft_time_limit=240,  # 4 minutes soft limit (sends exception)
    task_time_limit=300,  # 5 minutes hard limit (kills task)

    # Default retry policy
    task_default_retry_delay=60,  # 1 minute
    task_max_retries=3,

    # Result backend settings
    result_expires=3600,  # Keep results for 1 hour
    result_extended=True,  # Store task state info

    # Worker settings
    worker_max_tasks_per_child=100,  # Restart worker after 100 tasks (prevents memory leaks)
    worker_disable_rate_limits=False,

    # Beat scheduler settings
    beat_scheduler="celery.beat:PersistentScheduler",
    beat_max_loop_interval=60,

    # Beat schedule for periodic tasks
    beat_schedule={
        # Run aggregation every 5 minutes
        "aggregate-flows-5min": {
            "task": "app.workers.aggregation.aggregate_flows",
            "schedule": crontab(minute="*/5"),
            "args": (),
            "options": {
                "expires": 240,  # Task expires if not started within 4 minutes
                "queue": "default",
            }
        },
        # Run ML scoring after aggregation (offset by 1 minute)
        "score-anomalies": {
            "task": "app.workers.scoring.score_anomalies",
            "schedule": crontab(minute="1,6,11,16,21,26,31,36,41,46,51,56"),
            "args": (),
            "options": {
                "expires": 240,
                "queue": "default",
            }
        },
        # Generate alerts from scores (offset by 2 minutes)
        "generate-alerts": {
            "task": "app.workers.alerting.generate_alerts",
            "schedule": crontab(minute="2,7,12,17,22,27,32,37,42,47,52,57"),
            "args": (),
            "options": {
                "expires": 240,
                "queue": "default",
            }
        },
        # Cleanup old resolved alerts (daily at 3 AM)
        "cleanup-alerts-daily": {
            "task": "app.workers.alerting.cleanup_resolved_alerts",
            "schedule": crontab(hour=3, minute=0),
            "args": (30,),  # Keep resolved alerts for 30 days
            "options": {
                "expires": 3600,
                "queue": "default",
            }
        },
        # Check for alert escalation (every 15 minutes)
        "check-escalation": {
            "task": "app.workers.alerting.check_alert_escalation",
            "schedule": crontab(minute="*/15"),
            "args": (),
            "options": {
                "expires": 600,
                "queue": "default",
            }
        },
    },
)


# Signal handlers for structured logging
@signals.task_prerun.connect
def task_prerun_handler(sender=None, task_id=None, task=None, args=None, kwargs=None, **kw):
    """Log when a task starts."""
    logger.info(
        f"Task started: {task.name}",
        extra={
            "task_id": task_id,
            "task_name": task.name,
            "task_args": str(args)[:200],
            "event": "task_started",
        }
    )


@signals.task_postrun.connect
def task_postrun_handler(sender=None, task_id=None, task=None, args=None, kwargs=None, retval=None, state=None, **kw):
    """Log when a task completes."""
    logger.info(
        f"Task completed: {task.name} [{state}]",
        extra={
            "task_id": task_id,
            "task_name": task.name,
            "task_state": state,
            "event": "task_completed",
        }
    )


@signals.task_failure.connect
def task_failure_handler(sender=None, task_id=None, exception=None, args=None, kwargs=None, traceback=None, **kw):
    """Log when a task fails."""
    logger.error(
        f"Task failed: {sender.name} - {exception}",
        extra={
            "task_id": task_id,
            "task_name": sender.name if sender else "unknown",
            "exception": str(exception),
            "event": "task_failed",
        },
        exc_info=True
    )


@signals.task_retry.connect
def task_retry_handler(sender=None, reason=None, **kw):
    """Log when a task is retried."""
    logger.warning(
        f"Task retry: {sender.name} - {reason}",
        extra={
            "task_name": sender.name if sender else "unknown",
            "retry_reason": str(reason),
            "event": "task_retry",
        }
    )


@signals.worker_ready.connect
def worker_ready_handler(sender=None, **kw):
    """Log when worker is ready."""
    logger.info(
        "Celery worker ready",
        extra={
            "event": "worker_ready",
            "timestamp": datetime.utcnow().isoformat(),
        }
    )
