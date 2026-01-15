"""
ML Scoring - scores feature vectors using trained models.

Features:
- Real-time scoring of new feature vectors
- Feature contribution calculation (explainability)
- Concept drift detection
- Learning mode support
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.ml.model_manager import ModelManager, ModelVersion
from app.ml.training import FEATURE_COLUMNS

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://netsentinel:netsentinel_dev@localhost:5432/netsentinel"
)

# Scoring thresholds
DEFAULT_ANOMALY_THRESHOLD = 0.0  # Isolation Forest: negative = anomaly
LEARNING_MODE_DAYS = 7  # Days before alerts are generated


class ConceptDriftDetector:
    """
    Detects concept drift by comparing score distributions over time.

    Uses a simple approach: compare recent score statistics to training baseline.
    If the distribution shifts significantly, flag potential drift.
    """

    def __init__(
        self,
        baseline_mean: float,
        baseline_std: float,
        drift_threshold: float = 2.0,  # Standard deviations
        window_size: int = 288,  # 24 hours of 5-min windows
    ):
        self.baseline_mean = baseline_mean
        self.baseline_std = baseline_std
        self.drift_threshold = drift_threshold
        self.window_size = window_size
        self.recent_scores: List[float] = []

    def add_score(self, score: float):
        """Add a new score to the tracking window."""
        self.recent_scores.append(score)
        if len(self.recent_scores) > self.window_size:
            self.recent_scores.pop(0)

    def check_drift(self) -> Tuple[bool, Dict[str, Any]]:
        """
        Check if concept drift has occurred.

        Returns:
            Tuple of (drift_detected, drift_info)
        """
        if len(self.recent_scores) < self.window_size // 2:
            return False, {"status": "insufficient_data", "samples": len(self.recent_scores)}

        current_mean = np.mean(self.recent_scores)
        current_std = np.std(self.recent_scores)

        # Calculate z-score of mean shift
        if self.baseline_std > 0:
            z_score = abs(current_mean - self.baseline_mean) / self.baseline_std
        else:
            z_score = 0.0

        drift_detected = z_score > self.drift_threshold

        return drift_detected, {
            "status": "drift_detected" if drift_detected else "stable",
            "baseline_mean": self.baseline_mean,
            "baseline_std": self.baseline_std,
            "current_mean": float(current_mean),
            "current_std": float(current_std),
            "z_score": float(z_score),
            "threshold": self.drift_threshold,
            "samples": len(self.recent_scores),
        }


class ScoringEngine:
    """
    Scores feature vectors for anomaly detection.
    """

    def __init__(
        self,
        db_url: Optional[str] = None,
        model_storage_path: Optional[str] = None,
    ):
        self.db_url = db_url or DATABASE_URL
        self.engine = create_engine(self.db_url, pool_pre_ping=True)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.model_manager = ModelManager(storage_path=model_storage_path)
        self._drift_detectors: Dict[str, ConceptDriftDetector] = {}
        self._site_metadata: Dict[str, Dict[str, Any]] = {}

    def _get_model(self, site_id: str) -> Tuple[Optional[Any], Optional[ModelVersion]]:
        """Load model for a site."""
        return self.model_manager.load_model(site_id, model_type="isolation_forest")

    def _initialize_drift_detector(self, site_id: str, model_version: ModelVersion):
        """Initialize drift detector from model metrics."""
        if site_id in self._drift_detectors:
            return

        metrics = model_version.metrics
        score_stats = metrics.get("score_stats", {})

        baseline_mean = score_stats.get("mean", 0.0)
        baseline_std = score_stats.get("std", 1.0)

        self._drift_detectors[site_id] = ConceptDriftDetector(
            baseline_mean=baseline_mean,
            baseline_std=baseline_std,
        )

    def is_learning_mode(self, site_id: str, db: Session) -> bool:
        """
        Check if a site is still in learning mode.

        Learning mode suppresses alerts for the first N days after deployment.
        """
        # Check cached metadata
        if site_id in self._site_metadata:
            first_seen = self._site_metadata[site_id].get("first_seen")
            if first_seen:
                days_active = (datetime.utcnow() - first_seen).days
                return days_active < LEARNING_MODE_DAYS

        # Query database
        result = db.execute(
            text("""
                SELECT
                    MIN(window_start) as first_window,
                    created_at as site_created
                FROM features_5m f
                JOIN sites s ON f.site_id = s.id
                WHERE f.site_id = :site_id
                GROUP BY s.created_at
            """),
            {"site_id": site_id}
        )
        row = result.fetchone()

        if row:
            first_seen = row[0] or row[1]
            self._site_metadata[site_id] = {"first_seen": first_seen}
            days_active = (datetime.utcnow() - first_seen).days
            return days_active < LEARNING_MODE_DAYS

        return True  # Default to learning mode if no data

    def calculate_feature_contributions(
        self,
        model_artifact: Dict[str, Any],
        feature_values: np.ndarray,
        scaled_values: np.ndarray,
    ) -> Dict[str, float]:
        """
        Calculate which features contributed most to the anomaly score.

        Uses a simple approach: features with values far from the mean
        (in terms of scaled values) contribute more.
        """
        feature_columns = model_artifact["feature_columns"]

        # Calculate contribution as absolute deviation from 0 (mean after scaling)
        contributions = {}
        total_deviation = np.sum(np.abs(scaled_values))

        if total_deviation > 0:
            for i, col in enumerate(feature_columns):
                contributions[col] = float(abs(scaled_values[i]) / total_deviation)
        else:
            for col in feature_columns:
                contributions[col] = 0.0

        # Sort by contribution
        return dict(sorted(contributions.items(), key=lambda x: x[1], reverse=True)[:10])

    def score_features(
        self,
        site_id: str,
        features: Dict[str, Any],
        asset_id: str,
    ) -> Tuple[float, bool, Dict[str, Any]]:
        """
        Score a single feature vector.

        Args:
            site_id: Site ID
            features: Feature dictionary
            asset_id: Asset ID

        Returns:
            Tuple of (anomaly_score, is_anomaly, explanation)
        """
        model_artifact, model_version = self._get_model(site_id)

        if model_artifact is None:
            # No model trained yet - return neutral score
            return 0.1, False, {"status": "no_model"}

        model = model_artifact["model"]
        scaler = model_artifact["scaler"]
        feature_columns = model_artifact["feature_columns"]
        threshold = model_artifact.get("threshold", 0.0)

        # Extract features in correct order
        feature_values = np.array([
            float(features.get(col, 0.0) or 0.0)
            for col in feature_columns
        ]).reshape(1, -1)

        # Scale features
        scaled_values = scaler.transform(feature_values)
        scaled_values = np.nan_to_num(scaled_values, nan=0.0)

        # Get raw score (decision_function returns the signed distance to hyperplane)
        raw_score = model.decision_function(scaled_values)[0]

        # Convert to anomaly score (0-1, higher = more anomalous)
        # Isolation Forest: negative scores are anomalies
        # We invert and normalize to 0-1 scale
        anomaly_score = self._normalize_score(raw_score)

        # Determine if anomaly
        is_anomaly = raw_score < threshold

        # Calculate feature contributions
        contributions = self.calculate_feature_contributions(
            model_artifact, feature_values[0], scaled_values[0]
        )

        # Update drift detector
        self._initialize_drift_detector(site_id, model_version)
        self._drift_detectors[site_id].add_score(raw_score)

        explanation = {
            "model_version": model_version.version,
            "model_id": model_version.model_id,
            "raw_score": float(raw_score),
            "threshold": float(threshold),
            "feature_contributions": contributions,
        }

        return anomaly_score, is_anomaly, explanation

    def _normalize_score(self, raw_score: float) -> float:
        """
        Normalize Isolation Forest score to 0-1 range.

        Isolation Forest decision_function returns values roughly in [-0.5, 0.5]
        for normal data, more negative for anomalies.
        """
        # Sigmoid-like transformation centered at 0
        # More negative raw_score -> higher anomaly_score
        normalized = 1 / (1 + np.exp(raw_score * 5))
        return float(np.clip(normalized, 0.0, 1.0))

    def score_window(
        self,
        site_id: str,
        window_start: datetime,
    ) -> List[Dict[str, Any]]:
        """
        Score all feature vectors for a site in a given time window.

        Args:
            site_id: Site ID
            window_start: Start of the 5-minute window

        Returns:
            List of scoring results
        """
        db = self.SessionLocal()
        results = []

        try:
            # Check learning mode
            in_learning_mode = self.is_learning_mode(site_id, db)

            # Fetch feature vectors
            columns = ", ".join(FEATURE_COLUMNS)
            result = db.execute(
                text(f"""
                    SELECT asset_id, {columns}
                    FROM features_5m
                    WHERE site_id = :site_id
                    AND window_start = :window_start
                """),
                {"site_id": site_id, "window_start": window_start}
            )

            rows = result.fetchall()

            for row in rows:
                asset_id = str(row[0])
                features = {
                    col: row[i + 1]
                    for i, col in enumerate(FEATURE_COLUMNS)
                }

                anomaly_score, is_anomaly, explanation = self.score_features(
                    site_id=site_id,
                    features=features,
                    asset_id=asset_id,
                )

                # Suppress anomaly flag in learning mode
                if in_learning_mode:
                    is_anomaly = False
                    explanation["learning_mode"] = True

                results.append({
                    "site_id": site_id,
                    "asset_id": asset_id,
                    "window_start": window_start,
                    "anomaly_score": anomaly_score,
                    "is_anomaly": is_anomaly,
                    "explanation": explanation,
                })

        finally:
            db.close()

        return results

    def check_drift(self, site_id: str) -> Tuple[bool, Dict[str, Any]]:
        """Check for concept drift on a site."""
        if site_id not in self._drift_detectors:
            return False, {"status": "no_detector"}

        return self._drift_detectors[site_id].check_drift()

    def save_scores(
        self,
        scores: List[Dict[str, Any]],
    ):
        """
        Save scoring results to anomaly_scores_5m table.
        """
        if not scores:
            return

        db = self.SessionLocal()
        try:
            for score_result in scores:
                explanation = score_result.get("explanation", {})

                db.execute(
                    text("""
                        INSERT INTO anomaly_scores_5m (
                            window_start, site_id, asset_id,
                            model_id, model_version,
                            anomaly_score, raw_score,
                            threshold_used, is_anomaly,
                            feature_contributions,
                            scored_at
                        ) VALUES (
                            :window_start, :site_id, :asset_id,
                            :model_id, :model_version,
                            :anomaly_score, :raw_score,
                            :threshold_used, :is_anomaly,
                            :feature_contributions,
                            NOW()
                        )
                        ON CONFLICT (site_id, asset_id, window_start) DO UPDATE SET
                            anomaly_score = EXCLUDED.anomaly_score,
                            raw_score = EXCLUDED.raw_score,
                            is_anomaly = EXCLUDED.is_anomaly,
                            feature_contributions = EXCLUDED.feature_contributions,
                            scored_at = NOW()
                    """),
                    {
                        "window_start": score_result["window_start"],
                        "site_id": score_result["site_id"],
                        "asset_id": score_result["asset_id"],
                        "model_id": explanation.get("model_id", "unknown"),
                        "model_version": explanation.get("model_version", 0),
                        "anomaly_score": score_result["anomaly_score"],
                        "raw_score": explanation.get("raw_score", 0.0),
                        "threshold_used": explanation.get("threshold", 0.0),
                        "is_anomaly": score_result["is_anomaly"],
                        "feature_contributions": str(explanation.get("feature_contributions", {})),
                    }
                )

            db.commit()
            logger.info(f"Saved {len(scores)} anomaly scores")

        except Exception as e:
            logger.error(f"Failed to save scores: {e}")
            db.rollback()
            raise
        finally:
            db.close()
