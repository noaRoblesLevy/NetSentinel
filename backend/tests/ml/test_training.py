"""
Tests for ML training pipeline.
"""

import numpy as np
import pytest
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from sklearn.ensemble import IsolationForest


class TestIsolationForestTraining:
    """Tests for Isolation Forest model training."""

    def test_model_training_basic(self):
        """Test basic model training with synthetic data."""
        # Generate synthetic normal data
        np.random.seed(42)
        n_samples = 500
        n_features = 23  # Same as FEATURE_COLUMNS

        # Normal data (centered around 0)
        X_normal = np.random.randn(n_samples, n_features) * 0.5

        # Add some anomalies (outliers)
        n_anomalies = 25
        X_anomalies = np.random.randn(n_anomalies, n_features) * 3 + 5

        X = np.vstack([X_normal, X_anomalies])

        # Train model
        model = IsolationForest(
            contamination=0.05,
            n_estimators=100,
            random_state=42,
        )
        model.fit(X)

        # Score all samples
        scores = model.decision_function(X)
        predictions = model.predict(X)

        # Check that anomalies are detected
        anomaly_predictions = predictions[-n_anomalies:]
        detected_anomalies = (anomaly_predictions == -1).sum()

        # At least 50% of anomalies should be detected
        assert detected_anomalies >= n_anomalies * 0.5, \
            f"Only {detected_anomalies}/{n_anomalies} anomalies detected"

    def test_model_scoring_consistency(self):
        """Test that scoring is consistent across multiple calls."""
        np.random.seed(42)
        X = np.random.randn(100, 10)

        model = IsolationForest(n_estimators=50, random_state=42)
        model.fit(X)

        # Score the same data twice
        scores1 = model.decision_function(X)
        scores2 = model.decision_function(X)

        # Scores should be identical
        np.testing.assert_array_equal(scores1, scores2)

    def test_model_handles_edge_cases(self):
        """Test model behavior with edge cases."""
        np.random.seed(42)

        # Minimal data
        X_min = np.random.randn(50, 5)
        model = IsolationForest(n_estimators=10, random_state=42)
        model.fit(X_min)

        # Score single sample
        single = np.random.randn(1, 5)
        score = model.decision_function(single)
        assert len(score) == 1

        # Score with zero values
        zeros = np.zeros((1, 5))
        score_zeros = model.decision_function(zeros)
        assert not np.isnan(score_zeros[0])


class TestModelManager:
    """Tests for model storage and versioning."""

    def test_save_and_load_model(self):
        """Test saving and loading a model."""
        from app.ml.model_manager import ModelManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ModelManager(storage_path=tmpdir)

            # Create a simple model
            model = IsolationForest(n_estimators=10, random_state=42)
            X = np.random.randn(50, 5)
            model.fit(X)

            # Save
            model_artifact = {"model": model, "scaler": None, "feature_columns": ["a", "b", "c", "d", "e"]}
            version = manager.save_model(
                model=model_artifact,
                site_id="test-site",
                model_type="isolation_forest",
                metrics={"samples": 50},
                config={"n_estimators": 10},
            )

            assert version.version == 1
            assert version.site_id == "test-site"
            assert "test-site" in version.model_id

            # Load
            loaded, loaded_version = manager.load_model("test-site", "isolation_forest")
            assert loaded is not None
            assert loaded_version.version == 1

            # Verify model works
            score = loaded["model"].decision_function(X[:1])
            assert len(score) == 1

    def test_versioning(self):
        """Test that versions increment correctly."""
        from app.ml.model_manager import ModelManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ModelManager(storage_path=tmpdir)

            model = IsolationForest(n_estimators=10, random_state=42)
            X = np.random.randn(50, 5)
            model.fit(X)
            artifact = {"model": model, "scaler": None, "feature_columns": []}

            # Save multiple versions
            v1 = manager.save_model(artifact, "site1", metrics={})
            v2 = manager.save_model(artifact, "site1", metrics={})
            v3 = manager.save_model(artifact, "site1", metrics={})

            assert v1.version == 1
            assert v2.version == 2
            assert v3.version == 3

            # List versions
            versions = manager.list_versions("site1")
            assert len(versions) == 3
            assert versions[0].version == 3  # Most recent first

    def test_hash_computation(self):
        """Test that model hashes are computed correctly."""
        from app.ml.model_manager import ModelManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ModelManager(storage_path=tmpdir)

            model1 = IsolationForest(n_estimators=10, random_state=42)
            model2 = IsolationForest(n_estimators=10, random_state=42)

            X = np.random.randn(50, 5)
            model1.fit(X)
            model2.fit(X)

            # Same training should produce same hash
            hash1 = manager._compute_hash(model1)
            hash2 = manager._compute_hash(model2)
            assert hash1 == hash2

            # Different model should produce different hash
            model3 = IsolationForest(n_estimators=20, random_state=42)
            model3.fit(X)
            hash3 = manager._compute_hash(model3)
            assert hash1 != hash3


class TestConceptDriftDetection:
    """Tests for concept drift detection."""

    def test_no_drift_stable_distribution(self):
        """Test that stable distribution shows no drift."""
        from app.ml.scoring import ConceptDriftDetector

        detector = ConceptDriftDetector(
            baseline_mean=0.0,
            baseline_std=1.0,
            drift_threshold=2.0,
            window_size=100,
        )

        # Add scores from similar distribution
        np.random.seed(42)
        for _ in range(100):
            detector.add_score(np.random.randn())

        drift_detected, info = detector.check_drift()

        assert not drift_detected
        assert info["status"] == "stable"
        assert abs(info["current_mean"]) < 0.5  # Should be close to 0

    def test_drift_detected_shifted_distribution(self):
        """Test that drift is detected when distribution shifts."""
        from app.ml.scoring import ConceptDriftDetector

        detector = ConceptDriftDetector(
            baseline_mean=0.0,
            baseline_std=1.0,
            drift_threshold=2.0,
            window_size=100,
        )

        # Add scores from shifted distribution
        np.random.seed(42)
        for _ in range(100):
            detector.add_score(np.random.randn() + 5.0)  # Shifted by 5

        drift_detected, info = detector.check_drift()

        assert drift_detected
        assert info["status"] == "drift_detected"
        assert info["z_score"] > 2.0

    def test_insufficient_data(self):
        """Test handling of insufficient data."""
        from app.ml.scoring import ConceptDriftDetector

        detector = ConceptDriftDetector(
            baseline_mean=0.0,
            baseline_std=1.0,
            window_size=100,
        )

        # Add too few samples
        for _ in range(10):
            detector.add_score(0.0)

        drift_detected, info = detector.check_drift()

        assert not drift_detected
        assert info["status"] == "insufficient_data"


class TestScoringEngine:
    """Tests for scoring engine."""

    def test_score_normalization(self):
        """Test that scores are normalized to 0-1 range."""
        from app.ml.scoring import ScoringEngine

        engine = ScoringEngine()

        # Test normalization function
        # Very negative (anomaly) -> high score
        assert engine._normalize_score(-1.0) > 0.9

        # Positive (normal) -> low score
        assert engine._normalize_score(0.5) < 0.2

        # Zero -> middle
        assert 0.4 < engine._normalize_score(0.0) < 0.6

    def test_feature_contributions(self):
        """Test feature contribution calculation."""
        from app.ml.scoring import ScoringEngine

        engine = ScoringEngine()

        model_artifact = {
            "model": None,
            "scaler": None,
            "feature_columns": ["a", "b", "c"],
        }

        feature_values = np.array([10.0, 20.0, 30.0])
        scaled_values = np.array([1.0, 2.0, 3.0])  # Sum = 6

        contributions = engine.calculate_feature_contributions(
            model_artifact, feature_values, scaled_values
        )

        # Check contributions sum to ~1
        total = sum(contributions.values())
        assert abs(total - 1.0) < 0.01

        # c should have highest contribution (3/6 = 0.5)
        assert contributions["c"] == pytest.approx(0.5, abs=0.01)


class TestSyntheticAnomalyDetection:
    """Test anomaly detection with synthetic attack patterns."""

    @pytest.fixture
    def trained_model(self):
        """Create a trained model with normal traffic patterns."""
        from sklearn.preprocessing import StandardScaler

        np.random.seed(42)

        # Simulate normal network traffic features
        n_samples = 1000

        # Normal traffic: low entropy, consistent patterns
        normal_data = {
            "flows_in": np.random.poisson(50, n_samples),
            "flows_out": np.random.poisson(100, n_samples),
            "bytes_in": np.random.exponential(10000, n_samples),
            "bytes_out": np.random.exponential(50000, n_samples),
            "unique_dst_ports": np.random.poisson(5, n_samples),
            "unique_dst_ips": np.random.poisson(10, n_samples),
            "dst_port_entropy": np.random.uniform(0.5, 2.0, n_samples),  # Low entropy
            "dst_ip_entropy": np.random.uniform(1.0, 3.0, n_samples),
        }

        X = np.column_stack([normal_data[k] for k in sorted(normal_data.keys())])

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        model = IsolationForest(contamination=0.05, n_estimators=100, random_state=42)
        model.fit(X_scaled)

        return model, scaler, sorted(normal_data.keys())

    def test_detect_port_scan(self, trained_model):
        """Test detection of port scanning behavior."""
        model, scaler, feature_cols = trained_model

        # Port scan: many unique destination ports, high entropy
        port_scan = {
            "bytes_in": 1000,
            "bytes_out": 500,
            "dst_ip_entropy": 0.5,  # Single target
            "dst_port_entropy": 8.0,  # Very high - scanning many ports
            "flows_in": 10,
            "flows_out": 1000,  # Many outbound connections
            "unique_dst_ips": 1,
            "unique_dst_ports": 500,  # Many ports
        }

        X = np.array([[port_scan[k] for k in feature_cols]])
        X_scaled = scaler.transform(X)

        score = model.decision_function(X_scaled)[0]
        prediction = model.predict(X_scaled)[0]

        # Should be detected as anomaly
        assert prediction == -1, f"Port scan not detected as anomaly (score: {score})"

    def test_detect_data_exfiltration(self, trained_model):
        """Test detection of data exfiltration pattern."""
        model, scaler, feature_cols = trained_model

        # Data exfiltration: very high outbound bytes
        exfil = {
            "bytes_in": 1000,
            "bytes_out": 10000000,  # 10MB - very high
            "dst_ip_entropy": 0.0,  # Single destination
            "dst_port_entropy": 0.0,  # Single port (443)
            "flows_in": 10,
            "flows_out": 100,
            "unique_dst_ips": 1,
            "unique_dst_ports": 1,
        }

        X = np.array([[exfil[k] for k in feature_cols]])
        X_scaled = scaler.transform(X)

        score = model.decision_function(X_scaled)[0]
        prediction = model.predict(X_scaled)[0]

        # Should be detected as anomaly
        assert prediction == -1, f"Data exfil not detected as anomaly (score: {score})"

    def test_detect_lateral_movement(self, trained_model):
        """Test detection of lateral movement pattern."""
        model, scaler, feature_cols = trained_model

        # Lateral movement: many internal connections
        lateral = {
            "bytes_in": 5000,
            "bytes_out": 5000,
            "dst_ip_entropy": 7.0,  # Many different IPs
            "dst_port_entropy": 1.5,  # Few ports (22, 445, 3389)
            "flows_in": 50,
            "flows_out": 500,  # Many outbound
            "unique_dst_ips": 200,  # Scanning many hosts
            "unique_dst_ports": 3,
        }

        X = np.array([[lateral[k] for k in feature_cols]])
        X_scaled = scaler.transform(X)

        score = model.decision_function(X_scaled)[0]
        prediction = model.predict(X_scaled)[0]

        # Should be detected as anomaly
        assert prediction == -1, f"Lateral movement not detected (score: {score})"

    def test_normal_traffic_not_flagged(self, trained_model):
        """Test that normal traffic is not flagged as anomalous."""
        model, scaler, feature_cols = trained_model

        # Normal web browsing
        normal = {
            "bytes_in": 50000,
            "bytes_out": 10000,
            "dst_ip_entropy": 2.5,
            "dst_port_entropy": 1.0,
            "flows_in": 50,
            "flows_out": 100,
            "unique_dst_ips": 15,
            "unique_dst_ports": 3,
        }

        X = np.array([[normal[k] for k in feature_cols]])
        X_scaled = scaler.transform(X)

        prediction = model.predict(X_scaled)[0]

        # Should NOT be flagged as anomaly
        assert prediction == 1, "Normal traffic incorrectly flagged as anomaly"
