"""
ML scoring worker - scores feature vectors using trained Isolation Forest models.

This worker reads from features_5m and generates anomaly scores in anomaly_scores_5m.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://netsentinel:netsentinel_dev@localhost:5432/netsentinel")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)

# Lazy import to avoid circular imports
_scoring_engine = None


def get_scoring_engine():
    """Get or create the scoring engine singleton."""
    global _scoring_engine
    if _scoring_engine is None:
        from app.ml.scoring import ScoringEngine
        _scoring_engine = ScoringEngine()
    return _scoring_engine


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def score_anomalies(self, site_id: Optional[str] = None, window_start: Optional[str] = None):
    """
    Score feature vectors for anomalies using trained ML models.

    Uses Isolation Forest models trained per-site. Falls back to placeholder
    scoring if no model is available for a site.

    Args:
        site_id: Optional specific site to process (default: all active sites)
        window_start: Optional specific window to process (ISO format string)
    """
    db = SessionLocal()

    try:
        # Get the most recent unscored window
        if window_start:
            w_start = datetime.fromisoformat(window_start)
        else:
            # Get most recent complete window
            now = datetime.utcnow()
            minute = (now.minute // 5) * 5
            w_end = now.replace(minute=minute, second=0, microsecond=0)
            w_start = w_end - timedelta(minutes=5)

        logger.info(f"Scoring anomalies for window {w_start}")

        # Get sites to process
        if site_id:
            sites = [(site_id,)]
        else:
            result = db.execute(text("SELECT id FROM sites WHERE status = 'active'"))
            sites = result.fetchall()

        total_scored = 0
        total_anomalies = 0

        for (current_site_id,) in sites:
            try:
                scored, anomalies = _score_site_window(db, str(current_site_id), w_start)
                total_scored += scored
                total_anomalies += anomalies
            except Exception as e:
                logger.error(f"Failed to score site {current_site_id}: {e}")
                continue

        db.commit()
        logger.info(
            f"Scoring complete for window {w_start}: "
            f"{total_scored} scored, {total_anomalies} anomalies detected"
        )

    except Exception as e:
        logger.error(f"Scoring failed: {e}")
        db.rollback()
        raise self.retry(exc=e)
    finally:
        db.close()


def _score_site_window(db, site_id: str, window_start: datetime) -> tuple:
    """
    Score all feature vectors for a site in a given window.

    Returns:
        Tuple of (scored_count, anomaly_count)
    """
    scoring_engine = get_scoring_engine()

    # Score the window using the ML engine
    try:
        scores = scoring_engine.score_window(site_id, window_start)

        if not scores:
            logger.debug(f"No features to score for site {site_id} window {window_start}")
            return 0, 0

        # Save scores
        scoring_engine.save_scores(scores)

        anomaly_count = sum(1 for s in scores if s["is_anomaly"])
        logger.info(
            f"Scored {len(scores)} vectors for site {site_id}, "
            f"{anomaly_count} anomalies"
        )

        return len(scores), anomaly_count

    except Exception as e:
        logger.warning(f"ML scoring failed for site {site_id}, using fallback: {e}")
        return _fallback_score(db, site_id, window_start)


def _fallback_score(db, site_id: str, window_start: datetime) -> tuple:
    """
    Fallback scoring when no model is available.

    Assigns neutral scores to all features.
    """
    # Get unscored feature vectors
    result = db.execute(
        text("""
            SELECT f.asset_id, f.window_start
            FROM features_5m f
            LEFT JOIN anomaly_scores_5m s
                ON f.site_id = s.site_id
                AND f.asset_id = s.asset_id
                AND f.window_start = s.window_start
            WHERE f.site_id = :site_id
            AND f.window_start = :window_start
            AND s.asset_id IS NULL
        """),
        {"site_id": site_id, "window_start": window_start}
    )

    unscored = result.fetchall()

    if not unscored:
        return 0, 0

    for (asset_id, w_start) in unscored:
        db.execute(
            text("""
                INSERT INTO anomaly_scores_5m (
                    window_start, site_id, asset_id,
                    model_id, model_version,
                    anomaly_score, raw_score,
                    threshold_used, is_anomaly,
                    scored_at
                ) VALUES (
                    :window_start, :site_id, :asset_id,
                    'fallback', 0,
                    0.1, 0.0,
                    0.0, false,
                    NOW()
                )
                ON CONFLICT (site_id, asset_id, window_start) DO NOTHING
            """),
            {
                "window_start": w_start,
                "site_id": site_id,
                "asset_id": asset_id
            }
        )

    logger.info(f"Fallback scored {len(unscored)} vectors for site {site_id}")
    return len(unscored), 0


@celery_app.task(bind=True, max_retries=3, default_retry_delay=300)
def train_models(self, site_id: Optional[str] = None, days: int = 14):
    """
    Train Isolation Forest models for sites.

    Args:
        site_id: Optional specific site to train (default: all active sites)
        days: Number of days of historical data to use
    """
    from app.ml.training import TrainingPipeline

    pipeline = TrainingPipeline()

    try:
        if site_id:
            logger.info(f"Training model for site {site_id}")
            model_version, metrics = pipeline.train_model(site_id, days=days)
            if model_version:
                logger.info(f"Trained model {model_version.model_id}")
            else:
                logger.warning(f"Training failed for site {site_id}: {metrics}")
        else:
            logger.info("Training models for all active sites")
            results = pipeline.train_all_sites(days=days)
            for sid, (mv, metrics) in results.items():
                if mv:
                    logger.info(f"Trained model {mv.model_id}")
                else:
                    logger.warning(f"Training failed for site {sid}: {metrics}")

    except Exception as e:
        logger.error(f"Training failed: {e}")
        raise self.retry(exc=e)


@celery_app.task
def check_concept_drift(site_id: str):
    """
    Check for concept drift on a site.

    Should be run periodically to detect when models need retraining.
    """
    scoring_engine = get_scoring_engine()
    drift_detected, drift_info = scoring_engine.check_drift(site_id)

    if drift_detected:
        logger.warning(f"Concept drift detected for site {site_id}: {drift_info}")
        # Optionally trigger retraining
        train_models.delay(site_id=site_id)
    else:
        logger.info(f"No drift detected for site {site_id}: {drift_info}")

    return drift_info
