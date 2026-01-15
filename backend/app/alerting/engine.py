"""
Alert Generation Engine - sophisticated alert generation with persistence rules.

Features:
- Threshold-based alerting with persistence rules
- Feature deviation explanations vs baseline
- Alert deduplication within time windows
- Severity classification
"""

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://netsentinel:netsentinel_dev@localhost:5432/netsentinel"
)

# Alert threshold configuration
CRITICAL_THRESHOLD = 0.95  # Single window triggers alert
HIGH_THRESHOLD = 0.85      # 3 consecutive windows triggers alert
MEDIUM_THRESHOLD = 0.70    # 5 consecutive windows triggers alert
LOW_THRESHOLD = 0.50       # Informational only

# Persistence windows required for each threshold
PERSISTENCE_WINDOWS = {
    "critical": 1,
    "high": 3,
    "medium": 5,
}

# Deduplication window
DEDUP_WINDOW_HOURS = 2


@dataclass
class FeatureDeviation:
    """Represents a feature's deviation from baseline."""
    feature_name: str
    current_value: float
    baseline_value: float
    deviation_pct: float
    deviation_multiplier: float
    direction: str  # "increase" or "decrease"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "feature": self.feature_name,
            "current": self.current_value,
            "baseline": self.baseline_value,
            "deviation_pct": self.deviation_pct,
            "multiplier": self.deviation_multiplier,
            "direction": self.direction,
        }

    def to_human_readable(self) -> str:
        """Generate human-readable deviation description."""
        if self.deviation_multiplier >= 2:
            return f"{self.feature_name} {self.deviation_multiplier:.1f}x"
        elif self.deviation_pct >= 100:
            return f"{self.feature_name} +{self.deviation_pct:.0f}%"
        elif self.deviation_pct <= -50:
            return f"{self.feature_name} {self.deviation_pct:.0f}%"
        else:
            return f"{self.feature_name} {'↑' if self.direction == 'increase' else '↓'}{abs(self.deviation_pct):.0f}%"


@dataclass
class AlertCandidate:
    """Represents a potential alert before deduplication."""
    site_id: str
    asset_id: str
    asset_name: str
    asset_ip: str
    severity: str
    alert_type: str
    peak_score: float
    avg_score: float
    window_start: datetime
    window_end: datetime
    consecutive_windows: int
    feature_deviations: List[FeatureDeviation]
    raw_explanation: Dict[str, Any]
    dedup_key: str = field(default="")

    def __post_init__(self):
        if not self.dedup_key:
            self.dedup_key = self._compute_dedup_key()

    def _compute_dedup_key(self) -> str:
        """Compute deduplication key from asset and top features."""
        # Use top 3 feature names for signature
        top_features = sorted(
            self.feature_deviations,
            key=lambda x: abs(x.deviation_pct),
            reverse=True
        )[:3]
        feature_sig = "_".join(f.feature_name for f in top_features)

        key_str = f"{self.asset_id}:{self.alert_type}:{feature_sig}"
        return hashlib.md5(key_str.encode()).hexdigest()[:16]

    def to_explanation_json(self) -> Dict[str, Any]:
        """Generate structured explanation JSON."""
        return {
            "summary": self._generate_summary(),
            "severity_reason": self._get_severity_reason(),
            "top_deviations": [d.to_dict() for d in self.feature_deviations[:5]],
            "statistics": {
                "peak_score": self.peak_score,
                "avg_score": self.avg_score,
                "consecutive_windows": self.consecutive_windows,
                "window_start": self.window_start.isoformat(),
                "window_end": self.window_end.isoformat(),
            },
            "raw_contributions": self.raw_explanation,
        }

    def _generate_summary(self) -> str:
        """Generate human-readable summary."""
        deviation_strs = [d.to_human_readable() for d in self.feature_deviations[:3]]
        return f"Anomalous behavior: {', '.join(deviation_strs)}"

    def _get_severity_reason(self) -> str:
        """Explain why this severity was assigned."""
        if self.severity == "critical":
            return f"Single window score of {self.peak_score:.2f} exceeds critical threshold ({CRITICAL_THRESHOLD})"
        elif self.severity == "high":
            return f"Score exceeded {HIGH_THRESHOLD} for {self.consecutive_windows} consecutive windows"
        elif self.severity == "medium":
            return f"Score exceeded {MEDIUM_THRESHOLD} for {self.consecutive_windows} consecutive windows"
        else:
            return f"Score of {self.peak_score:.2f} indicates potential anomaly"


class AlertEngine:
    """
    Generates alerts from anomaly scores with persistence and deduplication.
    """

    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or DATABASE_URL
        self.engine = create_engine(self.db_url, pool_pre_ping=True)
        self.SessionLocal = sessionmaker(bind=self.engine)

    def get_asset_baseline(
        self,
        db: Session,
        site_id: str,
        asset_id: str,
        days: int = 7,
    ) -> Dict[str, float]:
        """
        Get baseline statistics for an asset.

        Returns mean values for key features over the past N days.
        """
        result = db.execute(
            text("""
                SELECT
                    AVG(flows_in) as flows_in,
                    AVG(flows_out) as flows_out,
                    AVG(bytes_in) as bytes_in,
                    AVG(bytes_out) as bytes_out,
                    AVG(unique_src_ips) as unique_src_ips,
                    AVG(unique_dst_ips) as unique_dst_ips,
                    AVG(unique_src_ports) as unique_src_ports,
                    AVG(unique_dst_ports) as unique_dst_ports,
                    AVG(dst_port_entropy) as dst_port_entropy,
                    AVG(dst_ip_entropy) as dst_ip_entropy,
                    AVG(internal_external_ratio) as internal_external_ratio,
                    AVG(tcp_flows) as tcp_flows,
                    AVG(udp_flows) as udp_flows
                FROM features_5m
                WHERE site_id = :site_id
                AND asset_id = :asset_id
                AND window_start >= NOW() - INTERVAL ':days days'
                AND window_start < NOW() - INTERVAL '1 hour'
            """.replace(":days", str(days))),
            {"site_id": site_id, "asset_id": asset_id}
        )

        row = result.fetchone()
        if not row:
            return {}

        return {
            k: float(v) if v is not None else 0.0
            for k, v in row._mapping.items()
        }

    def get_current_features(
        self,
        db: Session,
        site_id: str,
        asset_id: str,
        window_start: datetime,
    ) -> Dict[str, float]:
        """Get current feature values for an asset."""
        result = db.execute(
            text("""
                SELECT
                    flows_in, flows_out, bytes_in, bytes_out,
                    unique_src_ips, unique_dst_ips,
                    unique_src_ports, unique_dst_ports,
                    dst_port_entropy, dst_ip_entropy,
                    internal_external_ratio,
                    tcp_flows, udp_flows
                FROM features_5m
                WHERE site_id = :site_id
                AND asset_id = :asset_id
                AND window_start = :window_start
            """),
            {"site_id": site_id, "asset_id": asset_id, "window_start": window_start}
        )

        row = result.fetchone()
        if not row:
            return {}

        return {
            k: float(v) if v is not None else 0.0
            for k, v in row._mapping.items()
        }

    def calculate_deviations(
        self,
        current: Dict[str, float],
        baseline: Dict[str, float],
    ) -> List[FeatureDeviation]:
        """Calculate feature deviations from baseline."""
        deviations = []

        for feature, current_val in current.items():
            baseline_val = baseline.get(feature, 0.0)

            if baseline_val == 0:
                if current_val > 0:
                    # New activity where there was none
                    deviation = FeatureDeviation(
                        feature_name=feature,
                        current_value=current_val,
                        baseline_value=baseline_val,
                        deviation_pct=float('inf'),
                        deviation_multiplier=float('inf'),
                        direction="increase",
                    )
                    deviations.append(deviation)
                continue

            deviation_pct = ((current_val - baseline_val) / baseline_val) * 100
            multiplier = current_val / baseline_val if baseline_val != 0 else 1.0
            direction = "increase" if current_val > baseline_val else "decrease"

            # Only include significant deviations
            if abs(deviation_pct) >= 50 or multiplier >= 2 or multiplier <= 0.5:
                deviations.append(FeatureDeviation(
                    feature_name=feature,
                    current_value=current_val,
                    baseline_value=baseline_val,
                    deviation_pct=deviation_pct,
                    deviation_multiplier=multiplier,
                    direction=direction,
                ))

        # Sort by absolute deviation
        deviations.sort(key=lambda x: abs(x.deviation_pct), reverse=True)

        return deviations

    def check_persistence(
        self,
        db: Session,
        site_id: str,
        asset_id: str,
        threshold: float,
        required_windows: int,
    ) -> Tuple[bool, int, float, float, datetime, datetime]:
        """
        Check if anomaly persists for required number of consecutive windows.

        Returns:
            (triggered, consecutive_count, peak_score, avg_score, start_time, end_time)
        """
        result = db.execute(
            text("""
                SELECT
                    window_start,
                    anomaly_score
                FROM anomaly_scores_5m
                WHERE site_id = :site_id
                AND asset_id = :asset_id
                AND window_start >= NOW() - INTERVAL '1 hour'
                ORDER BY window_start DESC
                LIMIT :limit
            """),
            {"site_id": site_id, "asset_id": asset_id, "limit": required_windows + 2}
        )

        rows = result.fetchall()

        if not rows:
            return False, 0, 0.0, 0.0, datetime.utcnow(), datetime.utcnow()

        consecutive = 0
        scores = []
        start_time = None
        end_time = rows[0][0]

        for window_start, score in rows:
            if score >= threshold:
                consecutive += 1
                scores.append(score)
                start_time = window_start
            else:
                break

        triggered = consecutive >= required_windows
        peak_score = max(scores) if scores else 0.0
        avg_score = sum(scores) / len(scores) if scores else 0.0

        return triggered, consecutive, peak_score, avg_score, start_time or end_time, end_time

    def is_duplicate(
        self,
        db: Session,
        site_id: str,
        dedup_key: str,
    ) -> bool:
        """Check if an alert with this dedup_key exists within the dedup window."""
        result = db.execute(
            text("""
                SELECT COUNT(*)
                FROM alerts
                WHERE site_id = :site_id
                AND dedup_key = :dedup_key
                AND created_at >= NOW() - INTERVAL ':hours hours'
                AND status NOT IN ('resolved', 'false_positive')
            """.replace(":hours", str(DEDUP_WINDOW_HOURS))),
            {"site_id": site_id, "dedup_key": dedup_key}
        )

        count = result.scalar()
        return count > 0

    def generate_alerts(
        self,
        site_id: Optional[str] = None,
    ) -> List[AlertCandidate]:
        """
        Generate alerts from recent anomaly scores.

        Args:
            site_id: Optional specific site to process

        Returns:
            List of created AlertCandidate objects
        """
        db = self.SessionLocal()
        alerts_created = []

        try:
            # Get sites to process
            if site_id:
                sites = [(site_id,)]
            else:
                result = db.execute(
                    text("SELECT id FROM sites WHERE status = 'active'")
                )
                sites = result.fetchall()

            for (current_site_id,) in sites:
                try:
                    site_alerts = self._generate_site_alerts(db, str(current_site_id))
                    alerts_created.extend(site_alerts)
                except Exception as e:
                    logger.error(f"Failed to generate alerts for site {current_site_id}: {e}")
                    continue

            db.commit()
            return alerts_created

        except Exception as e:
            logger.error(f"Alert generation failed: {e}")
            db.rollback()
            raise
        finally:
            db.close()

    def _generate_site_alerts(
        self,
        db: Session,
        site_id: str,
    ) -> List[AlertCandidate]:
        """Generate alerts for a single site."""
        alerts = []

        # Get recent high scores
        result = db.execute(
            text("""
                SELECT DISTINCT ON (s.asset_id)
                    s.site_id, s.asset_id, s.window_start,
                    s.anomaly_score, s.feature_contributions,
                    a.ip as asset_ip, a.hostname, a.custom_name
                FROM anomaly_scores_5m s
                JOIN assets a ON s.asset_id = a.id
                WHERE s.site_id = :site_id
                AND s.anomaly_score >= :low_threshold
                AND s.window_start >= NOW() - INTERVAL '30 minutes'
                ORDER BY s.asset_id, s.anomaly_score DESC
            """),
            {"site_id": site_id, "low_threshold": LOW_THRESHOLD}
        )

        candidates = result.fetchall()

        for candidate in candidates:
            alert = self._evaluate_candidate(db, candidate)
            if alert:
                alerts.append(alert)

        return alerts

    def _evaluate_candidate(
        self,
        db: Session,
        candidate,
    ) -> Optional[AlertCandidate]:
        """Evaluate a candidate and create alert if thresholds met."""
        site_id = str(candidate.site_id)
        asset_id = str(candidate.asset_id)
        score = candidate.anomaly_score
        window_start = candidate.window_start

        # Determine severity and check persistence
        severity = None
        triggered = False
        consecutive = 0
        peak_score = score
        avg_score = score
        start_time = window_start
        end_time = window_start + timedelta(minutes=5)

        # Check critical threshold (single window)
        if score >= CRITICAL_THRESHOLD:
            severity = "critical"
            triggered = True
            consecutive = 1

        # Check high threshold (3 consecutive)
        if not triggered:
            triggered, consecutive, peak_score, avg_score, start_time, end_time = \
                self.check_persistence(db, site_id, asset_id, HIGH_THRESHOLD, PERSISTENCE_WINDOWS["high"])
            if triggered:
                severity = "high"

        # Check medium threshold (5 consecutive)
        if not triggered:
            triggered, consecutive, peak_score, avg_score, start_time, end_time = \
                self.check_persistence(db, site_id, asset_id, MEDIUM_THRESHOLD, PERSISTENCE_WINDOWS["medium"])
            if triggered:
                severity = "medium"

        if not triggered:
            return None

        # Get baseline and current features for explanation
        baseline = self.get_asset_baseline(db, site_id, asset_id)
        current = self.get_current_features(db, site_id, asset_id, window_start)
        deviations = self.calculate_deviations(current, baseline)

        # Parse raw feature contributions
        raw_explanation = {}
        if candidate.feature_contributions:
            try:
                if isinstance(candidate.feature_contributions, str):
                    raw_explanation = json.loads(candidate.feature_contributions.replace("'", '"'))
                else:
                    raw_explanation = candidate.feature_contributions
            except (json.JSONDecodeError, TypeError):
                raw_explanation = {}

        # Create alert candidate
        asset_name = candidate.custom_name or candidate.hostname or str(candidate.asset_ip)

        alert = AlertCandidate(
            site_id=site_id,
            asset_id=asset_id,
            asset_name=asset_name,
            asset_ip=str(candidate.asset_ip),
            severity=severity,
            alert_type="anomaly_detection",
            peak_score=peak_score,
            avg_score=avg_score,
            window_start=start_time,
            window_end=end_time,
            consecutive_windows=consecutive,
            feature_deviations=deviations,
            raw_explanation=raw_explanation,
        )

        # Check deduplication
        if self.is_duplicate(db, site_id, alert.dedup_key):
            logger.debug(f"Duplicate alert suppressed for asset {asset_id}")
            return None

        # Insert alert into database
        self._insert_alert(db, alert)

        logger.info(
            f"Alert created: {severity} severity for asset {asset_name} "
            f"(score: {peak_score:.2f}, windows: {consecutive})"
        )

        return alert

    def _insert_alert(self, db: Session, alert: AlertCandidate):
        """Insert alert into database."""
        explanation_json = alert.to_explanation_json()

        # Generate title
        title = f"{alert.severity.upper()}: Anomalous behavior on {alert.asset_name}"

        # Generate description
        if alert.feature_deviations:
            top_deviations = [d.to_human_readable() for d in alert.feature_deviations[:3]]
            description = f"Detected: {', '.join(top_deviations)}. Peak score: {alert.peak_score:.2f}"
        else:
            description = f"Anomaly score {alert.peak_score:.2f} exceeded threshold"

        # Suggested actions based on deviation types
        suggested_actions = self._generate_suggested_actions(alert)

        db.execute(
            text("""
                INSERT INTO alerts (
                    site_id, asset_id, alert_type, severity, status,
                    title, description, peak_score, avg_score,
                    start_time, end_time, explanation,
                    suggested_actions, dedup_key, created_at
                ) VALUES (
                    :site_id, :asset_id, :alert_type, :severity, 'open',
                    :title, :description, :peak_score, :avg_score,
                    :start_time, :end_time, :explanation,
                    :suggested_actions, :dedup_key, NOW()
                )
            """),
            {
                "site_id": alert.site_id,
                "asset_id": alert.asset_id,
                "alert_type": alert.alert_type,
                "severity": alert.severity,
                "title": title,
                "description": description,
                "peak_score": alert.peak_score,
                "avg_score": alert.avg_score,
                "start_time": alert.window_start,
                "end_time": alert.window_end,
                "explanation": json.dumps(explanation_json),
                "suggested_actions": suggested_actions,
                "dedup_key": alert.dedup_key,
            }
        )

    def _generate_suggested_actions(self, alert: AlertCandidate) -> List[str]:
        """Generate suggested actions based on deviation patterns."""
        actions = []

        for deviation in alert.feature_deviations[:5]:
            feature = deviation.feature_name

            if feature == "dst_port_entropy" and deviation.direction == "increase":
                actions.append("Investigate potential port scanning activity")
            elif feature == "unique_dst_ips" and deviation.direction == "increase":
                actions.append("Review destination IPs for reconnaissance patterns")
            elif feature == "bytes_out" and deviation.deviation_multiplier >= 5:
                actions.append("Check for potential data exfiltration")
            elif feature == "unique_dst_ports" and deviation.direction == "increase":
                actions.append("Analyze connection patterns for lateral movement")
            elif feature == "external_dst_count" and deviation.direction == "increase":
                actions.append("Verify external connections are authorized")
            elif feature == "internal_external_ratio" and deviation.direction == "decrease":
                actions.append("Review increase in external communications")

        # Default actions
        if not actions:
            actions.append("Review network traffic patterns for this asset")
            actions.append("Check for unauthorized applications")

        return list(set(actions))[:5]  # Dedupe and limit
