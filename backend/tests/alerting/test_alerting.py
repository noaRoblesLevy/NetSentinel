"""
Tests for alert generation and notification system.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch


class TestFeatureDeviation:
    """Tests for FeatureDeviation class."""

    def test_deviation_to_human_readable_multiplier(self):
        """Test human-readable format for large multipliers."""
        from app.alerting.engine import FeatureDeviation

        deviation = FeatureDeviation(
            feature_name="bytes_out",
            current_value=400000,
            baseline_value=50000,
            deviation_pct=700,
            deviation_multiplier=8.0,
            direction="increase",
        )

        readable = deviation.to_human_readable()
        assert "8.0x" in readable
        assert "bytes_out" in readable

    def test_deviation_to_human_readable_percentage(self):
        """Test human-readable format for percentage changes."""
        from app.alerting.engine import FeatureDeviation

        deviation = FeatureDeviation(
            feature_name="unique_dst_ips",
            current_value=36,
            baseline_value=12,
            deviation_pct=200,
            deviation_multiplier=3.0,
            direction="increase",
        )

        readable = deviation.to_human_readable()
        # Should show multiplier since it's >= 2
        assert "3.0x" in readable

    def test_deviation_to_human_readable_decrease(self):
        """Test human-readable format for decreases."""
        from app.alerting.engine import FeatureDeviation

        deviation = FeatureDeviation(
            feature_name="flows_in",
            current_value=10,
            baseline_value=100,
            deviation_pct=-90,
            deviation_multiplier=0.1,
            direction="decrease",
        )

        readable = deviation.to_human_readable()
        assert "-90%" in readable or "↓" in readable

    def test_deviation_to_dict(self):
        """Test serialization to dict."""
        from app.alerting.engine import FeatureDeviation

        deviation = FeatureDeviation(
            feature_name="bytes_out",
            current_value=400000,
            baseline_value=50000,
            deviation_pct=700,
            deviation_multiplier=8.0,
            direction="increase",
        )

        d = deviation.to_dict()
        assert d["feature"] == "bytes_out"
        assert d["current"] == 400000
        assert d["baseline"] == 50000
        assert d["deviation_pct"] == 700
        assert d["multiplier"] == 8.0
        assert d["direction"] == "increase"


class TestAlertCandidate:
    """Tests for AlertCandidate class."""

    def test_dedup_key_generation(self):
        """Test that dedup keys are generated consistently."""
        from app.alerting.engine import AlertCandidate, FeatureDeviation

        deviations = [
            FeatureDeviation("bytes_out", 100, 10, 900, 10.0, "increase"),
            FeatureDeviation("unique_dst_ips", 50, 10, 400, 5.0, "increase"),
            FeatureDeviation("dst_port_entropy", 5.0, 1.5, 233, 3.3, "increase"),
        ]

        alert1 = AlertCandidate(
            site_id="site1",
            asset_id="asset1",
            asset_name="test",
            asset_ip="192.168.1.1",
            severity="high",
            alert_type="anomaly_detection",
            peak_score=0.9,
            avg_score=0.85,
            window_start=datetime.utcnow(),
            window_end=datetime.utcnow() + timedelta(minutes=5),
            consecutive_windows=3,
            feature_deviations=deviations,
            raw_explanation={},
        )

        alert2 = AlertCandidate(
            site_id="site1",
            asset_id="asset1",
            asset_name="test",
            asset_ip="192.168.1.1",
            severity="high",
            alert_type="anomaly_detection",
            peak_score=0.92,  # Different score
            avg_score=0.87,
            window_start=datetime.utcnow() + timedelta(minutes=5),  # Different time
            window_end=datetime.utcnow() + timedelta(minutes=10),
            consecutive_windows=4,
            feature_deviations=deviations,  # Same deviations
            raw_explanation={},
        )

        # Same asset + same top features = same dedup key
        assert alert1.dedup_key == alert2.dedup_key

    def test_dedup_key_different_features(self):
        """Test that different features produce different dedup keys."""
        from app.alerting.engine import AlertCandidate, FeatureDeviation

        base_args = {
            "site_id": "site1",
            "asset_id": "asset1",
            "asset_name": "test",
            "asset_ip": "192.168.1.1",
            "severity": "high",
            "alert_type": "anomaly_detection",
            "peak_score": 0.9,
            "avg_score": 0.85,
            "window_start": datetime.utcnow(),
            "window_end": datetime.utcnow() + timedelta(minutes=5),
            "consecutive_windows": 3,
            "raw_explanation": {},
        }

        alert1 = AlertCandidate(
            **base_args,
            feature_deviations=[
                FeatureDeviation("bytes_out", 100, 10, 900, 10.0, "increase"),
            ],
        )

        alert2 = AlertCandidate(
            **base_args,
            feature_deviations=[
                FeatureDeviation("dst_port_entropy", 5.0, 1.5, 233, 3.3, "increase"),
            ],
        )

        # Different features = different dedup key
        assert alert1.dedup_key != alert2.dedup_key

    def test_explanation_json_generation(self):
        """Test explanation JSON structure."""
        from app.alerting.engine import AlertCandidate, FeatureDeviation

        deviations = [
            FeatureDeviation("bytes_out", 400000, 50000, 700, 8.0, "increase"),
        ]

        alert = AlertCandidate(
            site_id="site1",
            asset_id="asset1",
            asset_name="test-asset",
            asset_ip="192.168.1.1",
            severity="high",
            alert_type="anomaly_detection",
            peak_score=0.92,
            avg_score=0.88,
            window_start=datetime(2026, 1, 15, 16, 15, 0),
            window_end=datetime(2026, 1, 15, 16, 30, 0),
            consecutive_windows=3,
            feature_deviations=deviations,
            raw_explanation={},
        )

        explanation = alert.to_explanation_json()

        assert "summary" in explanation
        assert "severity_reason" in explanation
        assert "top_deviations" in explanation
        assert "statistics" in explanation
        assert len(explanation["top_deviations"]) == 1
        assert explanation["statistics"]["peak_score"] == 0.92
        assert explanation["statistics"]["consecutive_windows"] == 3


class TestDeviationCalculation:
    """Tests for feature deviation calculations."""

    def test_calculate_deviations_basic(self):
        """Test basic deviation calculation."""
        from app.alerting.engine import AlertEngine

        engine = AlertEngine.__new__(AlertEngine)

        current = {
            "bytes_out": 400000,
            "unique_dst_ips": 48,
            "flows_out": 100,
        }

        baseline = {
            "bytes_out": 50000,
            "unique_dst_ips": 12,
            "flows_out": 100,  # No change
        }

        deviations = engine.calculate_deviations(current, baseline)

        # Should only include significant deviations
        feature_names = [d.feature_name for d in deviations]
        assert "bytes_out" in feature_names
        assert "unique_dst_ips" in feature_names
        assert "flows_out" not in feature_names  # No significant change

    def test_calculate_deviations_zero_baseline(self):
        """Test deviation when baseline is zero."""
        from app.alerting.engine import AlertEngine

        engine = AlertEngine.__new__(AlertEngine)

        current = {"new_feature": 100}
        baseline = {"new_feature": 0}

        deviations = engine.calculate_deviations(current, baseline)

        # Should detect new activity
        assert len(deviations) == 1
        assert deviations[0].feature_name == "new_feature"
        assert deviations[0].deviation_pct == float('inf')

    def test_calculate_deviations_decrease(self):
        """Test deviation for decrease."""
        from app.alerting.engine import AlertEngine

        engine = AlertEngine.__new__(AlertEngine)

        current = {"flows_in": 10}
        baseline = {"flows_in": 100}

        deviations = engine.calculate_deviations(current, baseline)

        assert len(deviations) == 1
        assert deviations[0].direction == "decrease"
        assert deviations[0].deviation_pct == -90


class TestPersistenceRules:
    """Tests for alert persistence rules."""

    def test_critical_single_window(self):
        """Test that critical threshold triggers on single window."""
        from app.alerting.engine import CRITICAL_THRESHOLD

        # Score >= 0.95 should trigger critical alert immediately
        assert CRITICAL_THRESHOLD == 0.95

    def test_high_requires_persistence(self):
        """Test that high threshold requires consecutive windows."""
        from app.alerting.engine import HIGH_THRESHOLD, PERSISTENCE_WINDOWS

        assert HIGH_THRESHOLD == 0.85
        assert PERSISTENCE_WINDOWS["high"] == 3

    def test_medium_requires_more_persistence(self):
        """Test that medium threshold requires more consecutive windows."""
        from app.alerting.engine import MEDIUM_THRESHOLD, PERSISTENCE_WINDOWS

        assert MEDIUM_THRESHOLD == 0.70
        assert PERSISTENCE_WINDOWS["medium"] == 5


class TestNotificationPayload:
    """Tests for notification payload generation."""

    def test_webhook_payload_structure(self):
        """Test webhook payload has correct structure."""
        from app.alerting.notifications import EXAMPLE_WEBHOOK_PAYLOAD

        payload = EXAMPLE_WEBHOOK_PAYLOAD

        assert payload["event"] == "alert.created"
        assert "timestamp" in payload
        assert "alert" in payload

        alert = payload["alert"]
        assert "id" in alert
        assert "site_id" in alert
        assert "asset_id" in alert
        assert "severity" in alert
        assert "score" in alert
        assert "time" in alert
        assert "deviations" in alert
        assert "explanation" in alert

        # Check score structure
        assert "peak" in alert["score"]
        assert "average" in alert["score"]

        # Check time structure
        assert "start" in alert["time"]
        assert "end" in alert["time"]
        assert "consecutive_windows" in alert["time"]

    def test_webhook_payload_deviations(self):
        """Test webhook payload deviation format."""
        from app.alerting.notifications import EXAMPLE_WEBHOOK_PAYLOAD

        deviations = EXAMPLE_WEBHOOK_PAYLOAD["alert"]["deviations"]

        assert len(deviations) >= 1
        deviation = deviations[0]

        assert "feature" in deviation
        assert "baseline" in deviation
        assert "current" in deviation
        assert "change_pct" in deviation
        assert "multiplier" in deviation


class TestNotificationService:
    """Tests for notification service."""

    def test_quiet_hours_during(self):
        """Test quiet hours detection - during quiet hours."""
        from app.alerting.notifications import NotificationService

        service = NotificationService.__new__(NotificationService)

        # Mock current time to be 23:00
        with patch('app.alerting.notifications.datetime') as mock_dt:
            mock_dt.utcnow.return_value = datetime(2026, 1, 15, 23, 0, 0)

            is_quiet = service.is_in_quiet_hours("22:00:00", "07:00:00")
            assert is_quiet

    def test_quiet_hours_outside(self):
        """Test quiet hours detection - outside quiet hours."""
        from app.alerting.notifications import NotificationService

        service = NotificationService.__new__(NotificationService)

        # Mock current time to be 14:00
        with patch('app.alerting.notifications.datetime') as mock_dt:
            mock_dt.utcnow.return_value = datetime(2026, 1, 15, 14, 0, 0)

            is_quiet = service.is_in_quiet_hours("22:00:00", "07:00:00")
            assert not is_quiet

    def test_quiet_hours_not_configured(self):
        """Test quiet hours when not configured."""
        from app.alerting.notifications import NotificationService

        service = NotificationService.__new__(NotificationService)

        is_quiet = service.is_in_quiet_hours(None, None)
        assert not is_quiet


class TestSuggestedActions:
    """Tests for suggested action generation."""

    def test_port_scan_actions(self):
        """Test suggested actions for port scanning pattern."""
        from app.alerting.engine import AlertEngine, AlertCandidate, FeatureDeviation

        engine = AlertEngine.__new__(AlertEngine)

        alert = AlertCandidate(
            site_id="site1",
            asset_id="asset1",
            asset_name="test",
            asset_ip="192.168.1.1",
            severity="high",
            alert_type="anomaly_detection",
            peak_score=0.9,
            avg_score=0.85,
            window_start=datetime.utcnow(),
            window_end=datetime.utcnow() + timedelta(minutes=5),
            consecutive_windows=3,
            feature_deviations=[
                FeatureDeviation("dst_port_entropy", 8.0, 1.5, 433, 5.3, "increase"),
            ],
            raw_explanation={},
        )

        actions = engine._generate_suggested_actions(alert)

        assert any("port scan" in a.lower() for a in actions)

    def test_data_exfil_actions(self):
        """Test suggested actions for data exfiltration pattern."""
        from app.alerting.engine import AlertEngine, AlertCandidate, FeatureDeviation

        engine = AlertEngine.__new__(AlertEngine)

        alert = AlertCandidate(
            site_id="site1",
            asset_id="asset1",
            asset_name="test",
            asset_ip="192.168.1.1",
            severity="critical",
            alert_type="anomaly_detection",
            peak_score=0.96,
            avg_score=0.96,
            window_start=datetime.utcnow(),
            window_end=datetime.utcnow() + timedelta(minutes=5),
            consecutive_windows=1,
            feature_deviations=[
                FeatureDeviation("bytes_out", 10000000, 50000, 19900, 200.0, "increase"),
            ],
            raw_explanation={},
        )

        actions = engine._generate_suggested_actions(alert)

        assert any("exfiltration" in a.lower() for a in actions)


class TestExampleAlertPayload:
    """Test example alert payload format."""

    def test_example_payload_is_valid_json(self):
        """Test that example payload is valid."""
        from app.alerting.notifications import EXAMPLE_WEBHOOK_PAYLOAD
        import json

        # Should be serializable
        serialized = json.dumps(EXAMPLE_WEBHOOK_PAYLOAD)
        deserialized = json.loads(serialized)

        assert deserialized == EXAMPLE_WEBHOOK_PAYLOAD

    def test_example_payload_has_realistic_values(self):
        """Test that example payload has realistic values."""
        from app.alerting.notifications import EXAMPLE_WEBHOOK_PAYLOAD

        alert = EXAMPLE_WEBHOOK_PAYLOAD["alert"]

        # Score should be between 0 and 1
        assert 0 <= alert["score"]["peak"] <= 1
        assert 0 <= alert["score"]["average"] <= 1

        # Severity should be valid
        assert alert["severity"] in ["low", "medium", "high", "critical"]

        # Consecutive windows should be positive
        assert alert["time"]["consecutive_windows"] > 0

        # Deviations should show increase
        for dev in alert["deviations"]:
            assert dev["current"] > dev["baseline"]
            assert dev["change_pct"] > 0
            assert dev["multiplier"] > 1
