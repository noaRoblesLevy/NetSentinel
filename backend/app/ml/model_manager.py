"""
Model Manager - handles model storage, versioning, and loading.

Models are stored with versioning based on timestamp and content hash.
Supports both filesystem and database storage for model artifacts.
"""

import hashlib
import json
import logging
import os
import pickle
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Default model storage path
MODEL_STORAGE_PATH = os.getenv("MODEL_STORAGE_PATH", "/app/models")


class ModelVersion:
    """Represents a versioned model artifact."""

    def __init__(
        self,
        model_id: str,
        version: int,
        site_id: str,
        model_type: str,
        created_at: datetime,
        content_hash: str,
        metrics: Dict[str, Any],
        config: Dict[str, Any],
    ):
        self.model_id = model_id
        self.version = version
        self.site_id = site_id
        self.model_type = model_type
        self.created_at = created_at
        self.content_hash = content_hash
        self.metrics = metrics
        self.config = config

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "version": self.version,
            "site_id": self.site_id,
            "model_type": self.model_type,
            "created_at": self.created_at.isoformat(),
            "content_hash": self.content_hash,
            "metrics": self.metrics,
            "config": self.config,
        }


class ModelManager:
    """
    Manages ML model lifecycle: training, storage, versioning, and loading.
    """

    def __init__(self, storage_path: Optional[str] = None, db: Optional[Session] = None):
        self.storage_path = Path(storage_path or MODEL_STORAGE_PATH)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.db = db
        self._model_cache: Dict[str, Tuple[Any, ModelVersion]] = {}

    def _compute_hash(self, model: Any) -> str:
        """Compute content hash for a model."""
        model_bytes = pickle.dumps(model)
        return hashlib.sha256(model_bytes).hexdigest()[:16]

    def _get_model_path(self, site_id: str, model_type: str, version: int) -> Path:
        """Get filesystem path for a model."""
        site_dir = self.storage_path / site_id
        site_dir.mkdir(parents=True, exist_ok=True)
        return site_dir / f"{model_type}_v{version}.pkl"

    def _get_metadata_path(self, site_id: str, model_type: str, version: int) -> Path:
        """Get filesystem path for model metadata."""
        site_dir = self.storage_path / site_id
        return site_dir / f"{model_type}_v{version}_meta.json"

    def save_model(
        self,
        model: Any,
        site_id: str,
        model_type: str = "isolation_forest",
        metrics: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> ModelVersion:
        """
        Save a model with versioning.

        Args:
            model: The trained model object
            site_id: Site ID this model belongs to
            model_type: Type of model (e.g., 'isolation_forest')
            metrics: Training metrics (contamination, samples, etc.)
            config: Model configuration/hyperparameters

        Returns:
            ModelVersion object with versioning info
        """
        content_hash = self._compute_hash(model)
        created_at = datetime.utcnow()

        # Get next version number
        version = self._get_next_version(site_id, model_type)

        # Create model ID
        model_id = f"{site_id}_{model_type}_v{version}"

        # Save to filesystem
        model_path = self._get_model_path(site_id, model_type, version)
        with open(model_path, "wb") as f:
            pickle.dump(model, f)

        # Create version metadata
        model_version = ModelVersion(
            model_id=model_id,
            version=version,
            site_id=site_id,
            model_type=model_type,
            created_at=created_at,
            content_hash=content_hash,
            metrics=metrics or {},
            config=config or {},
        )

        # Save metadata
        meta_path = self._get_metadata_path(site_id, model_type, version)
        with open(meta_path, "w") as f:
            json.dump(model_version.to_dict(), f, indent=2)

        # Save to database if available
        if self.db:
            self._save_to_db(model_version)

        logger.info(f"Saved model {model_id} (hash: {content_hash})")

        # Update cache
        cache_key = f"{site_id}_{model_type}"
        self._model_cache[cache_key] = (model, model_version)

        return model_version

    def _get_next_version(self, site_id: str, model_type: str) -> int:
        """Get the next version number for a model."""
        site_dir = self.storage_path / site_id
        if not site_dir.exists():
            return 1

        existing = list(site_dir.glob(f"{model_type}_v*.pkl"))
        if not existing:
            return 1

        versions = []
        for path in existing:
            try:
                v = int(path.stem.split("_v")[-1])
                versions.append(v)
            except ValueError:
                continue

        return max(versions) + 1 if versions else 1

    def load_model(
        self,
        site_id: str,
        model_type: str = "isolation_forest",
        version: Optional[int] = None,
    ) -> Tuple[Optional[Any], Optional[ModelVersion]]:
        """
        Load a model, optionally specifying version.

        Args:
            site_id: Site ID
            model_type: Type of model
            version: Specific version (default: latest)

        Returns:
            Tuple of (model, ModelVersion) or (None, None) if not found
        """
        cache_key = f"{site_id}_{model_type}"

        # Check cache first (for latest version only)
        if version is None and cache_key in self._model_cache:
            return self._model_cache[cache_key]

        # Determine version to load
        if version is None:
            version = self._get_latest_version(site_id, model_type)
            if version is None:
                return None, None

        # Load from filesystem
        model_path = self._get_model_path(site_id, model_type, version)
        meta_path = self._get_metadata_path(site_id, model_type, version)

        if not model_path.exists():
            logger.warning(f"Model not found: {model_path}")
            return None, None

        try:
            with open(model_path, "rb") as f:
                model = pickle.load(f)

            # Load metadata
            if meta_path.exists():
                with open(meta_path, "r") as f:
                    meta = json.load(f)
                model_version = ModelVersion(
                    model_id=meta["model_id"],
                    version=meta["version"],
                    site_id=meta["site_id"],
                    model_type=meta["model_type"],
                    created_at=datetime.fromisoformat(meta["created_at"]),
                    content_hash=meta["content_hash"],
                    metrics=meta.get("metrics", {}),
                    config=meta.get("config", {}),
                )
            else:
                # Create minimal version info
                model_version = ModelVersion(
                    model_id=f"{site_id}_{model_type}_v{version}",
                    version=version,
                    site_id=site_id,
                    model_type=model_type,
                    created_at=datetime.utcnow(),
                    content_hash="unknown",
                    metrics={},
                    config={},
                )

            # Cache if latest
            if version == self._get_latest_version(site_id, model_type):
                self._model_cache[cache_key] = (model, model_version)

            return model, model_version

        except Exception as e:
            logger.error(f"Failed to load model {model_path}: {e}")
            return None, None

    def _get_latest_version(self, site_id: str, model_type: str) -> Optional[int]:
        """Get the latest version number for a model."""
        site_dir = self.storage_path / site_id
        if not site_dir.exists():
            return None

        existing = list(site_dir.glob(f"{model_type}_v*.pkl"))
        if not existing:
            return None

        versions = []
        for path in existing:
            try:
                v = int(path.stem.split("_v")[-1])
                versions.append(v)
            except ValueError:
                continue

        return max(versions) if versions else None

    def _save_to_db(self, model_version: ModelVersion):
        """Save model metadata to database."""
        if not self.db:
            return

        try:
            self.db.execute(
                text("""
                    INSERT INTO ml_models (
                        id, site_id, model_type, version,
                        content_hash, metrics, config,
                        created_at, is_active
                    ) VALUES (
                        :model_id, :site_id, :model_type, :version,
                        :content_hash, :metrics, :config,
                        :created_at, true
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        is_active = true,
                        metrics = EXCLUDED.metrics
                """),
                {
                    "model_id": model_version.model_id,
                    "site_id": model_version.site_id,
                    "model_type": model_version.model_type,
                    "version": model_version.version,
                    "content_hash": model_version.content_hash,
                    "metrics": json.dumps(model_version.metrics),
                    "config": json.dumps(model_version.config),
                    "created_at": model_version.created_at,
                }
            )

            # Deactivate older versions
            self.db.execute(
                text("""
                    UPDATE ml_models
                    SET is_active = false
                    WHERE site_id = :site_id
                    AND model_type = :model_type
                    AND version < :version
                """),
                {
                    "site_id": model_version.site_id,
                    "model_type": model_version.model_type,
                    "version": model_version.version,
                }
            )

            self.db.commit()
        except Exception as e:
            logger.error(f"Failed to save model to database: {e}")
            self.db.rollback()

    def list_versions(self, site_id: str, model_type: str = "isolation_forest") -> List[ModelVersion]:
        """List all versions of a model for a site."""
        site_dir = self.storage_path / site_id
        if not site_dir.exists():
            return []

        versions = []
        for meta_path in sorted(site_dir.glob(f"{model_type}_v*_meta.json")):
            try:
                with open(meta_path, "r") as f:
                    meta = json.load(f)
                versions.append(ModelVersion(
                    model_id=meta["model_id"],
                    version=meta["version"],
                    site_id=meta["site_id"],
                    model_type=meta["model_type"],
                    created_at=datetime.fromisoformat(meta["created_at"]),
                    content_hash=meta["content_hash"],
                    metrics=meta.get("metrics", {}),
                    config=meta.get("config", {}),
                ))
            except Exception as e:
                logger.warning(f"Failed to load metadata {meta_path}: {e}")

        return sorted(versions, key=lambda v: v.version, reverse=True)

    def delete_old_versions(self, site_id: str, model_type: str, keep_versions: int = 5):
        """Delete old model versions, keeping the N most recent."""
        versions = self.list_versions(site_id, model_type)

        if len(versions) <= keep_versions:
            return

        for old_version in versions[keep_versions:]:
            model_path = self._get_model_path(site_id, model_type, old_version.version)
            meta_path = self._get_metadata_path(site_id, model_type, old_version.version)

            try:
                if model_path.exists():
                    model_path.unlink()
                if meta_path.exists():
                    meta_path.unlink()
                logger.info(f"Deleted old model version: {old_version.model_id}")
            except Exception as e:
                logger.error(f"Failed to delete {old_version.model_id}: {e}")

    def clear_cache(self, site_id: Optional[str] = None):
        """Clear the model cache."""
        if site_id:
            keys_to_remove = [k for k in self._model_cache if k.startswith(site_id)]
            for key in keys_to_remove:
                del self._model_cache[key]
        else:
            self._model_cache.clear()
