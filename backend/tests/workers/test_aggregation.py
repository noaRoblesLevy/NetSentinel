"""
Tests for the flow aggregation worker.
"""

import math
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from app.workers.aggregation import (
    calculate_entropy,
    get_window_boundaries,
    is_business_hours,
)


class TestCalculateEntropy:
    """Tests for Shannon entropy calculation."""

    def test_empty_counts(self):
        """Empty dict should return 0."""
        assert calculate_entropy({}) == 0.0

    def test_zero_total(self):
        """All zeros should return 0."""
        assert calculate_entropy({"a": 0, "b": 0}) == 0.0

    def test_single_value(self):
        """Single value (all same) should return 0 entropy."""
        assert calculate_entropy({"a": 100}) == 0.0

    def test_uniform_distribution(self):
        """Uniform distribution should return max entropy."""
        # 4 equal values: entropy = log2(4) = 2.0
        counts = {"a": 25, "b": 25, "c": 25, "d": 25}
        entropy = calculate_entropy(counts)
        assert abs(entropy - 2.0) < 0.001

    def test_binary_distribution(self):
        """Two equal values should return entropy of 1."""
        counts = {"a": 50, "b": 50}
        entropy = calculate_entropy(counts)
        assert abs(entropy - 1.0) < 0.001

    def test_skewed_distribution(self):
        """Skewed distribution should return lower entropy."""
        # 90% a, 10% b
        counts = {"a": 90, "b": 10}
        entropy = calculate_entropy(counts)
        # H = -0.9*log2(0.9) - 0.1*log2(0.1) ≈ 0.469
        assert 0.4 < entropy < 0.5

    def test_port_scan_pattern(self):
        """High entropy typical of port scanning."""
        # Many unique destinations with equal counts
        counts = {i: 1 for i in range(256)}
        entropy = calculate_entropy(counts)
        # Should be close to log2(256) = 8
        assert entropy > 7.9

    def test_normal_traffic_pattern(self):
        """Low entropy typical of normal traffic."""
        # Few ports heavily used
        counts = {80: 1000, 443: 800, 22: 50, 53: 30}
        entropy = calculate_entropy(counts)
        # Should be relatively low
        assert entropy < 2.0


class TestGetWindowBoundaries:
    """Tests for time window boundary calculation."""

    def test_exact_boundary(self):
        """Time exactly on boundary should use previous window."""
        ref_time = datetime(2024, 1, 15, 10, 5, 0)
        w_start, w_end = get_window_boundaries(ref_time)
        assert w_start == datetime(2024, 1, 15, 10, 0, 0)
        assert w_end == datetime(2024, 1, 15, 10, 5, 0)

    def test_mid_window(self):
        """Time in middle of window should use previous complete window."""
        ref_time = datetime(2024, 1, 15, 10, 7, 30)
        w_start, w_end = get_window_boundaries(ref_time)
        assert w_start == datetime(2024, 1, 15, 10, 0, 0)
        assert w_end == datetime(2024, 1, 15, 10, 5, 0)

    def test_near_end_of_window(self):
        """Time near end of window should use previous complete window."""
        ref_time = datetime(2024, 1, 15, 10, 9, 59)
        w_start, w_end = get_window_boundaries(ref_time)
        assert w_start == datetime(2024, 1, 15, 10, 0, 0)
        assert w_end == datetime(2024, 1, 15, 10, 5, 0)

    def test_hour_boundary(self):
        """Time at hour boundary should work correctly."""
        ref_time = datetime(2024, 1, 15, 11, 0, 0)
        w_start, w_end = get_window_boundaries(ref_time)
        assert w_start == datetime(2024, 1, 15, 10, 55, 0)
        assert w_end == datetime(2024, 1, 15, 11, 0, 0)

    def test_microseconds_stripped(self):
        """Microseconds should be stripped from result."""
        ref_time = datetime(2024, 1, 15, 10, 7, 30, 123456)
        w_start, w_end = get_window_boundaries(ref_time)
        assert w_start.microsecond == 0
        assert w_end.microsecond == 0


class TestIsBusinessHours:
    """Tests for business hours detection."""

    def test_weekday_morning_business(self):
        """9 AM on Monday should be business hours."""
        dt = datetime(2024, 1, 15, 9, 0, 0)  # Monday
        assert is_business_hours(dt) is True

    def test_weekday_afternoon_business(self):
        """3 PM on Wednesday should be business hours."""
        dt = datetime(2024, 1, 17, 15, 0, 0)  # Wednesday
        assert is_business_hours(dt) is True

    def test_weekday_early_morning(self):
        """6 AM on Tuesday should not be business hours."""
        dt = datetime(2024, 1, 16, 6, 0, 0)  # Tuesday
        assert is_business_hours(dt) is False

    def test_weekday_evening(self):
        """7 PM on Thursday should not be business hours."""
        dt = datetime(2024, 1, 18, 19, 0, 0)  # Thursday
        assert is_business_hours(dt) is False

    def test_saturday_afternoon(self):
        """2 PM on Saturday should not be business hours."""
        dt = datetime(2024, 1, 20, 14, 0, 0)  # Saturday
        assert is_business_hours(dt) is False

    def test_sunday_morning(self):
        """10 AM on Sunday should not be business hours."""
        dt = datetime(2024, 1, 21, 10, 0, 0)  # Sunday
        assert is_business_hours(dt) is False

    def test_boundary_start(self):
        """Exactly 9 AM should be business hours."""
        dt = datetime(2024, 1, 15, 9, 0, 0)
        assert is_business_hours(dt) is True

    def test_boundary_end(self):
        """Exactly 6 PM should not be business hours (exclusive)."""
        dt = datetime(2024, 1, 15, 18, 0, 0)
        assert is_business_hours(dt) is False


class TestSyntheticScenarios:
    """Test scenarios with synthetic flow data patterns."""

    def test_entropy_detects_port_scan(self):
        """
        Port scan pattern: one source hitting many destination ports.
        Should produce high destination port entropy.
        """
        # Simulate port scan: 1000 flows to different ports
        dst_port_counts = {port: 1 for port in range(1, 1001)}

        entropy = calculate_entropy(dst_port_counts)

        # log2(1000) ≈ 9.97, expect high entropy
        assert entropy > 9.0, "Port scan should produce high entropy"

    def test_entropy_detects_normal_web_traffic(self):
        """
        Normal web traffic: mostly 80/443 with occasional others.
        Should produce low destination port entropy.
        """
        dst_port_counts = {
            443: 5000,  # HTTPS - most common
            80: 2000,   # HTTP
            53: 100,    # DNS
            22: 10,     # SSH
        }

        entropy = calculate_entropy(dst_port_counts)

        # Should be low entropy due to concentration on 443
        assert entropy < 1.5, "Normal traffic should produce low entropy"

    def test_entropy_detects_data_exfiltration(self):
        """
        Data exfiltration pattern: consistent connection to single external IP.
        Should produce very low destination IP entropy.
        """
        # All traffic to single destination
        dst_ip_counts = {"192.168.1.100": 10000}

        entropy = calculate_entropy(dst_ip_counts)

        assert entropy == 0.0, "Single destination should have zero entropy"

    def test_entropy_detects_ddos_reflection(self):
        """
        DDoS reflection: many sources hitting single destination.
        Should produce high source IP entropy but low destination entropy.
        """
        # Many unique sources
        src_ip_counts = {f"10.0.0.{i}": 10 for i in range(1, 255)}
        # Single destination
        dst_ip_counts = {"192.168.1.1": 2540}

        src_entropy = calculate_entropy(src_ip_counts)
        dst_entropy = calculate_entropy(dst_ip_counts)

        assert src_entropy > 7.0, "Many sources should have high entropy"
        assert dst_entropy == 0.0, "Single destination should have zero entropy"

    def test_entropy_detects_lateral_movement(self):
        """
        Lateral movement: one internal host scanning many internal IPs.
        Should produce high destination IP entropy with internal pattern.
        """
        # Scanning internal /24 subnet
        dst_ip_counts = {f"10.0.1.{i}": 5 for i in range(1, 255)}

        entropy = calculate_entropy(dst_ip_counts)

        # log2(254) ≈ 7.99, expect high entropy
        assert entropy > 7.5, "Internal scan should produce high entropy"
