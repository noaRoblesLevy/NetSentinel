"""
Pytest configuration and fixtures for backend tests.
"""

import os
import pytest
from datetime import datetime, timedelta
from typing import List, Dict, Any

# Set test environment variables before importing app modules
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/1")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")


@pytest.fixture
def sample_flow_record() -> Dict[str, Any]:
    """Create a sample flow record for testing."""
    return {
        "src_ip": "192.168.1.100",
        "dst_ip": "8.8.8.8",
        "src_port": 54321,
        "dst_port": 443,
        "protocol": 6,  # TCP
        "bytes": 1500,
        "packets": 10,
        "tcp_flags": 0x18,  # ACK+PSH
        "is_internal_src": True,
        "is_internal_dst": False,
    }


@pytest.fixture
def sample_flows_batch() -> List[Dict[str, Any]]:
    """Create a batch of sample flows for testing aggregation."""
    base_time = datetime.utcnow().replace(second=0, microsecond=0)
    flows = []

    # Normal HTTPS traffic
    for i in range(100):
        flows.append({
            "src_ip": "192.168.1.100",
            "dst_ip": f"203.0.113.{i % 10}",
            "src_port": 50000 + i,
            "dst_port": 443,
            "protocol": 6,
            "bytes": 1000 + i * 10,
            "packets": 5 + i % 5,
            "tcp_flags": 0x18,
            "is_internal_src": True,
            "is_internal_dst": False,
        })

    # DNS queries
    for i in range(20):
        flows.append({
            "src_ip": "192.168.1.100",
            "dst_ip": "8.8.8.8",
            "src_port": 50000 + i,
            "dst_port": 53,
            "protocol": 17,  # UDP
            "bytes": 100,
            "packets": 1,
            "tcp_flags": 0,
            "is_internal_src": True,
            "is_internal_dst": False,
        })

    return flows


@pytest.fixture
def port_scan_flows() -> List[Dict[str, Any]]:
    """Create flows simulating a port scan attack."""
    flows = []

    # One source scanning many ports on one destination
    for port in range(1, 1025):
        flows.append({
            "src_ip": "192.168.1.200",
            "dst_ip": "192.168.1.50",
            "src_port": 45000 + port,
            "dst_port": port,
            "protocol": 6,
            "bytes": 60,  # SYN packet
            "packets": 1,
            "tcp_flags": 0x02,  # SYN only
            "is_internal_src": True,
            "is_internal_dst": True,
        })

    return flows


@pytest.fixture
def lateral_movement_flows() -> List[Dict[str, Any]]:
    """Create flows simulating lateral movement."""
    flows = []

    # One source connecting to many internal hosts
    for host in range(1, 255):
        for port in [22, 445, 3389]:  # SSH, SMB, RDP
            flows.append({
                "src_ip": "192.168.1.50",
                "dst_ip": f"192.168.1.{host}",
                "src_port": 50000 + host,
                "dst_port": port,
                "protocol": 6,
                "bytes": 200,
                "packets": 3,
                "tcp_flags": 0x02,  # SYN
                "is_internal_src": True,
                "is_internal_dst": True,
            })

    return flows


@pytest.fixture
def data_exfiltration_flows() -> List[Dict[str, Any]]:
    """Create flows simulating data exfiltration."""
    flows = []

    # Large outbound transfers to single destination
    for i in range(50):
        flows.append({
            "src_ip": "192.168.1.100",
            "dst_ip": "198.51.100.50",  # External C2 server
            "src_port": 50000 + i,
            "dst_port": 443,
            "protocol": 6,
            "bytes": 1000000 + i * 10000,  # Large transfers
            "packets": 1000,
            "tcp_flags": 0x18,
            "is_internal_src": True,
            "is_internal_dst": False,
        })

    return flows
