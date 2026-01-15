"""
ML scoring worker - scores feature vectors using trained models.

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


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def score_anomalies(self, site_id: Optional[str] = None, window_start: Optional[str] = None):
    """
    Score feature vectors for anomalies using trained ML models.

    This is a placeholder - full implementation will use scikit-learn Isolation Forest.

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

        for (current_site_id,) in sites:
            try:
                _score_site_window(db, current_site_id, w_start)
            except Exception as e:
                logger.error(f"Failed to score site {current_site_id}: {e}")
                continue

        db.commit()
        logger.info(f"Scoring complete for window {w_start}")

    except Exception as e:
        logger.error(f"Scoring failed: {e}")
        db.rollback()
        raise self.retry(exc=e)
    finally:
        db.close()


def _score_site_window(db, site_id: str, window_start: datetime):
    """
    Score all feature vectors for a site in a given window.

    Placeholder implementation - assigns score of 0.1 (normal) to all.
    Real implementation will load trained Isolation Forest model.
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
        logger.debug(f"No unscored features for site {site_id} window {window_start}")
        return

    # Placeholder: insert dummy scores (0.1 = normal)
    # Real implementation will:
    # 1. Load trained model for this site
    # 2. Extract feature vector
    # 3. Run model.predict() / model.score_samples()
    # 4. Calculate feature contributions

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
                    'placeholder_v1', 1,
                    0.1, -0.5,
                    0.7, false,
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

    logger.info(f"Scored {len(unscored)} feature vectors for site {site_id}")
