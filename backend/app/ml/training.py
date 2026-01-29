"""
ML Training Pipeline - trains Isolation Forest models per site.

Features:
- Training on configurable historical window (default: 14 days)
- Automatic feature scaling and selection
- Model versioning and persistence
- Training metrics tracking
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.ml.model_manager import ModelManager, ModelVersion
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Feature columns used for training
FEATURE_COLUMNS = [
    "flows_in",
    "flows_out",
    "bytes_in",
    "bytes_out",
    "packets_in",
    "packets_out",
    "unique_src_ips",
    "unique_dst_ips",
    "unique_src_ports",
    "unique_dst_ports",
    "internal_dst_count",
    "external_dst_count",
    "dst_port_entropy",
    "dst_ip_entropy",
    "src_port_entropy",
    "tcp_flows",
    "udp_flows",
    "icmp_flows",
    "avg_bytes_per_flow",
    "avg_packets_per_flow",
    "hour_of_day",
    "day_of_week",
    "internal_external_ratio",
]

# Default hyperparameters
DEFAULT_CONTAMINATION = 0.05  # Expected 5% anomalies
DEFAULT_N_ESTIMATORS = 100
DEFAULT_MAX_SAMPLES = "auto"
DEFAULT_RANDOM_STATE = 42

DATABASE_URL = settings.database_url


class TrainingPipeline:
    """
    Handles training Isolation Forest models for anomaly detection.
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

    def get_training_data(
        self,
        site_id: str,
        days: int = 14,
        min_samples: int = 100,
    ) -> Tuple[Optional[np.ndarray], Optional[List[str]], Dict[str, Any]]:
        """
        Fetch training data from features_5m table.

        Args:
            site_id: Site ID to train for
            days: Number of days of historical data
            min_samples: Minimum samples required for training

        Returns:
            Tuple of (feature_matrix, asset_ids, metadata)
        """
        db = self.SessionLocal()
        try:
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(days=days)

            # Build column selection
            columns = ", ".join(FEATURE_COLUMNS)

            result = db.execute(
                text(f"""
                    SELECT
                        asset_id,
                        {columns}
                    FROM features_5m
                    WHERE site_id = :site_id
                    AND window_start >= :start_time
                    AND window_start < :end_time
                    ORDER BY window_start ASC
                """),
                {"site_id": site_id, "start_time": start_time, "end_time": end_time}
            )

            rows = result.fetchall()

            if len(rows) < min_samples:
                logger.warning(
                    f"Insufficient data for site {site_id}: {len(rows)} < {min_samples}"
                )
                return None, None, {"error": "insufficient_data", "samples": len(rows)}

            # Extract features and asset IDs
            asset_ids = [str(row[0]) for row in rows]
            features = np.array([[float(v) if v is not None else 0.0 for v in row[1:]] for row in rows])

            # Calculate metadata
            metadata = {
                "samples": len(rows),
                "features": len(FEATURE_COLUMNS),
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "unique_assets": len(set(asset_ids)),
            }

            return features, asset_ids, metadata

        finally:
            db.close()

    def train_model(
        self,
        site_id: str,
        days: int = 14,
        contamination: float = DEFAULT_CONTAMINATION,
        n_estimators: int = DEFAULT_N_ESTIMATORS,
        max_samples: Any = DEFAULT_MAX_SAMPLES,
        random_state: int = DEFAULT_RANDOM_STATE,
    ) -> Tuple[Optional[ModelVersion], Dict[str, Any]]:
        """
        Train an Isolation Forest model for a site.

        Args:
            site_id: Site ID to train for
            days: Days of historical data to use
            contamination: Expected proportion of anomalies
            n_estimators: Number of trees in the forest
            max_samples: Samples per tree
            random_state: Random seed for reproducibility

        Returns:
            Tuple of (ModelVersion, training_metrics)
        """
        logger.info(f"Starting training for site {site_id}")

        # Fetch training data
        X, asset_ids, data_meta = self.get_training_data(site_id, days=days)

        if X is None:
            return None, data_meta

        # Scale features
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        # Handle NaN values (replace with 0)
        X_scaled = np.nan_to_num(X_scaled, nan=0.0, posinf=0.0, neginf=0.0)

        # Train Isolation Forest
        model = IsolationForest(
            contamination=contamination,
            n_estimators=n_estimators,
            max_samples=max_samples,
            random_state=random_state,
            n_jobs=-1,
        )

        logger.info(f"Fitting model on {X_scaled.shape[0]} samples, {X_scaled.shape[1]} features")
        model.fit(X_scaled)

        # Calculate training metrics
        scores = model.decision_function(X_scaled)
        predictions = model.predict(X_scaled)

        n_anomalies = (predictions == -1).sum()
        actual_contamination = n_anomalies / len(predictions)

        # Score distribution stats
        score_stats = {
            "mean": float(np.mean(scores)),
            "std": float(np.std(scores)),
            "min": float(np.min(scores)),
            "max": float(np.max(scores)),
            "p5": float(np.percentile(scores, 5)),
            "p25": float(np.percentile(scores, 25)),
            "p50": float(np.percentile(scores, 50)),
            "p75": float(np.percentile(scores, 75)),
            "p95": float(np.percentile(scores, 95)),
        }

        metrics = {
            **data_meta,
            "contamination_target": contamination,
            "contamination_actual": actual_contamination,
            "n_anomalies_train": int(n_anomalies),
            "score_stats": score_stats,
            "trained_at": datetime.utcnow().isoformat(),
        }

        config = {
            "n_estimators": n_estimators,
            "max_samples": str(max_samples),
            "contamination": contamination,
            "random_state": random_state,
            "feature_columns": FEATURE_COLUMNS,
        }

        # Save model with scaler
        model_artifact = {
            "model": model,
            "scaler": scaler,
            "feature_columns": FEATURE_COLUMNS,
            "threshold": model.offset_,
        }

        # Save to model manager
        model_version = self.model_manager.save_model(
            model=model_artifact,
            site_id=site_id,
            model_type="isolation_forest",
            metrics=metrics,
            config=config,
        )

        logger.info(
            f"Training complete for site {site_id}: "
            f"version={model_version.version}, "
            f"anomalies={n_anomalies}/{len(predictions)} ({actual_contamination:.2%})"
        )

        return model_version, metrics

    def train_all_sites(
        self,
        days: int = 14,
        **kwargs,
    ) -> Dict[str, Tuple[Optional[ModelVersion], Dict[str, Any]]]:
        """
        Train models for all active sites.

        Returns:
            Dict mapping site_id to (ModelVersion, metrics)
        """
        db = self.SessionLocal()
        results = {}

        try:
            result = db.execute(text("SELECT id FROM sites WHERE status = 'active'"))
            sites = [str(row[0]) for row in result.fetchall()]

            logger.info(f"Training models for {len(sites)} sites")

            for site_id in sites:
                try:
                    model_version, metrics = self.train_model(
                        site_id=site_id,
                        days=days,
                        **kwargs,
                    )
                    results[site_id] = (model_version, metrics)
                except Exception as e:
                    logger.error(f"Failed to train model for site {site_id}: {e}")
                    results[site_id] = (None, {"error": str(e)})

        finally:
            db.close()

        return results

    def get_feature_importance(
        self,
        site_id: str,
        n_samples: int = 1000,
    ) -> Dict[str, float]:
        """
        Estimate feature importance using permutation.

        Args:
            site_id: Site ID
            n_samples: Number of samples to use for estimation

        Returns:
            Dict mapping feature names to importance scores
        """
        # Load model
        model_artifact, model_version = self.model_manager.load_model(
            site_id=site_id,
            model_type="isolation_forest",
        )

        if model_artifact is None:
            return {}

        model = model_artifact["model"]
        scaler = model_artifact["scaler"]
        feature_columns = model_artifact["feature_columns"]

        # Get sample data
        X, _, _ = self.get_training_data(site_id, days=7)
        if X is None or len(X) < n_samples:
            return {}

        # Use subset
        idx = np.random.choice(len(X), min(n_samples, len(X)), replace=False)
        X_sample = X[idx]
        X_scaled = scaler.transform(X_sample)

        # Base scores
        base_scores = model.decision_function(X_scaled)
        base_mean = np.mean(base_scores)

        # Permutation importance
        importance = {}
        for i, col in enumerate(feature_columns):
            X_permuted = X_scaled.copy()
            np.random.shuffle(X_permuted[:, i])
            permuted_scores = model.decision_function(X_permuted)
            importance[col] = abs(np.mean(permuted_scores) - base_mean)

        # Normalize
        total = sum(importance.values())
        if total > 0:
            importance = {k: v / total for k, v in importance.items()}

        return dict(sorted(importance.items(), key=lambda x: x[1], reverse=True))
