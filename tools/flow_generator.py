#!/usr/bin/env python3
"""
NetFlow v9 Test Flow Generator for NetSentinel

Generates realistic network flow data and sends it to the collector
to test the full monitoring pipeline.
"""

import argparse
import random
import socket
import struct
import time
from datetime import datetime
from typing import List, Tuple

# NetFlow v9 constants
NETFLOW_V9_VERSION = 9
TEMPLATE_FLOWSET_ID = 0
DATA_FLOWSET_ID = 256  # Template ID for our data

# Common ports for realistic traffic
COMMON_PORTS = [80, 443, 22, 53, 8080, 3389, 21, 25, 110, 143, 993, 995, 8443]
DNS_SERVERS = ["8.8.8.8", "8.8.4.4", "1.1.1.1"]
CLOUD_IPS = ["52.84.123.45", "13.107.42.14", "172.217.14.78", "151.101.1.140"]

class NetFlowGenerator:
    """Generates and sends NetFlow v9 packets."""

    def __init__(self, collector_host: str, collector_port: int, site_id: str):
        self.collector_host = collector_host
        self.collector_port = collector_port
        self.site_id = site_id
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sequence = 0
        self.boot_time = int(time.time() * 1000) - 86400000  # 1 day ago

        # Internal network assets
        self.internal_ips = [
            "192.168.1.1",    # Router
            "192.168.1.10",   # Desktop
            "192.168.1.20",   # Laptop
            "192.168.1.50",   # NAS
            "192.168.1.100",  # Smart TV
        ]

        # Track flow patterns per device for anomaly generation
        self.device_baselines = {ip: self._create_baseline() for ip in self.internal_ips}

    def _create_baseline(self) -> dict:
        """Create baseline behavior for a device."""
        return {
            "avg_flows_per_min": random.randint(10, 50),
            "avg_bytes_per_flow": random.randint(1000, 50000),
            "common_ports": random.sample(COMMON_PORTS, k=random.randint(3, 6)),
            "common_destinations": random.sample(CLOUD_IPS + DNS_SERVERS, k=random.randint(2, 4)),
        }

    def _build_template_flowset(self) -> bytes:
        """Build NetFlow v9 template flowset."""
        # Template header
        template = struct.pack(">HH", TEMPLATE_FLOWSET_ID, 0)  # FlowSet ID, Length (placeholder)

        # Template record
        template += struct.pack(">HH", DATA_FLOWSET_ID, 13)  # Template ID, Field Count

        # Field definitions (Type, Length)
        fields = [
            (8, 4),    # IPV4_SRC_ADDR
            (12, 4),   # IPV4_DST_ADDR
            (7, 2),    # L4_SRC_PORT
            (11, 2),   # L4_DST_PORT
            (4, 1),    # PROTOCOL
            (1, 4),    # IN_BYTES
            (2, 4),    # IN_PKTS
            (22, 4),   # FIRST_SWITCHED
            (21, 4),   # LAST_SWITCHED
            (6, 1),    # TCP_FLAGS
            (10, 2),   # INPUT_SNMP
            (14, 2),   # OUTPUT_SNMP
            (5, 1),    # IP_TOS
        ]

        for field_type, field_len in fields:
            template += struct.pack(">HH", field_type, field_len)

        # Update length (must be multiple of 4)
        length = len(template)
        padding = (4 - length % 4) % 4
        template += b'\x00' * padding
        length += padding

        # Rewrite length
        template = struct.pack(">HH", TEMPLATE_FLOWSET_ID, length) + template[4:]

        return template

    def _ip_to_bytes(self, ip: str) -> bytes:
        """Convert IP string to bytes."""
        return socket.inet_aton(ip)

    def _generate_flow_record(self, src_ip: str, dst_ip: str,
                               src_port: int, dst_port: int,
                               protocol: int, bytes_count: int,
                               packets: int, duration_ms: int) -> bytes:
        """Generate a single flow record."""
        now_ms = int(time.time() * 1000)
        uptime = now_ms - self.boot_time
        first_switched = uptime - duration_ms
        last_switched = uptime

        tcp_flags = random.choice([0x10, 0x18, 0x11, 0x02]) if protocol == 6 else 0

        record = b""
        record += self._ip_to_bytes(src_ip)
        record += self._ip_to_bytes(dst_ip)
        record += struct.pack(">H", src_port)
        record += struct.pack(">H", dst_port)
        record += struct.pack(">B", protocol)
        record += struct.pack(">I", bytes_count)
        record += struct.pack(">I", packets)
        record += struct.pack(">I", first_switched)
        record += struct.pack(">I", last_switched)
        record += struct.pack(">B", tcp_flags)
        record += struct.pack(">H", 1)   # INPUT_SNMP
        record += struct.pack(">H", 2)   # OUTPUT_SNMP
        record += struct.pack(">B", 0)   # IP_TOS

        return record

    def _build_data_flowset(self, records: List[bytes]) -> bytes:
        """Build data flowset from records."""
        data = struct.pack(">HH", DATA_FLOWSET_ID, 0)  # FlowSet ID, Length (placeholder)

        for record in records:
            data += record

        # Padding to 4-byte boundary
        length = len(data)
        padding = (4 - length % 4) % 4
        data += b'\x00' * padding
        length += padding

        # Rewrite length
        data = struct.pack(">HH", DATA_FLOWSET_ID, length) + data[4:]

        return data

    def _build_packet(self, flowsets: List[bytes]) -> bytes:
        """Build complete NetFlow v9 packet."""
        now = int(time.time())
        uptime = (now * 1000) - self.boot_time

        # Count records (rough estimate)
        count = sum(len(fs) // 35 for fs in flowsets)

        # NetFlow v9 header: version(2) + count(2) + uptime(4) + unix_secs(4) + sequence(4) + source_id(4)
        header = struct.pack(">HHIIII",
            NETFLOW_V9_VERSION,
            count,
            uptime & 0xFFFFFFFF,  # Ensure 32-bit
            now,
            self.sequence,
            0  # Source ID
        )

        self.sequence += 1

        packet = header
        for flowset in flowsets:
            packet += flowset

        return packet

    def generate_normal_traffic(self, device_ip: str) -> List[bytes]:
        """Generate normal traffic patterns for a device."""
        baseline = self.device_baselines[device_ip]
        records = []

        num_flows = random.randint(
            baseline["avg_flows_per_min"] // 2,
            baseline["avg_flows_per_min"] * 2
        )

        for _ in range(num_flows):
            # Outbound traffic
            dst_ip = random.choice(baseline["common_destinations"] + CLOUD_IPS)
            dst_port = random.choice(baseline["common_ports"])
            src_port = random.randint(49152, 65535)
            protocol = 6 if dst_port in [80, 443, 22, 8080] else random.choice([6, 17])

            bytes_count = random.randint(
                baseline["avg_bytes_per_flow"] // 2,
                baseline["avg_bytes_per_flow"] * 2
            )
            packets = max(1, bytes_count // random.randint(500, 1500))
            duration = random.randint(100, 30000)

            records.append(self._generate_flow_record(
                device_ip, dst_ip, src_port, dst_port,
                protocol, bytes_count, packets, duration
            ))

            # Response traffic
            records.append(self._generate_flow_record(
                dst_ip, device_ip, dst_port, src_port,
                protocol, bytes_count // 2, packets // 2, duration
            ))

        return records

    def generate_anomalous_traffic(self, device_ip: str, anomaly_type: str) -> List[bytes]:
        """Generate anomalous traffic patterns."""
        records = []

        if anomaly_type == "port_scan":
            # Scanning many ports on few hosts
            target = random.choice(CLOUD_IPS)
            for port in random.sample(range(1, 1024), k=100):
                records.append(self._generate_flow_record(
                    device_ip, target, random.randint(49152, 65535), port,
                    6, random.randint(40, 100), 1, 50
                ))

        elif anomaly_type == "data_exfil":
            # Large outbound data transfer
            dst_ip = f"{random.randint(1,223)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"
            for _ in range(50):
                records.append(self._generate_flow_record(
                    device_ip, dst_ip, random.randint(49152, 65535), 443,
                    6, random.randint(1000000, 5000000), random.randint(1000, 5000), 5000
                ))

        elif anomaly_type == "c2_beacon":
            # Regular beaconing to suspicious IP
            c2_ip = f"{random.randint(1,223)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"
            for _ in range(20):
                records.append(self._generate_flow_record(
                    device_ip, c2_ip, random.randint(49152, 65535), random.choice([443, 8080, 8443]),
                    6, random.randint(100, 500), 1, 100
                ))

        elif anomaly_type == "crypto_mining":
            # Connections to mining pools
            pool_ports = [3333, 4444, 5555, 8888, 9999]
            pool_ip = f"{random.randint(1,223)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"
            for _ in range(30):
                records.append(self._generate_flow_record(
                    device_ip, pool_ip, random.randint(49152, 65535), random.choice(pool_ports),
                    6, random.randint(500, 2000), random.randint(5, 20), 60000
                ))

        return records

    def send_packet(self, packet: bytes):
        """Send packet to collector."""
        self.sock.sendto(packet, (self.collector_host, self.collector_port))

    def run(self, duration_seconds: int = 300, anomaly_probability: float = 0.05):
        """Run the flow generator."""
        print(f"Starting NetFlow generator")
        print(f"  Collector: {self.collector_host}:{self.collector_port}")
        print(f"  Duration: {duration_seconds}s")
        print(f"  Anomaly probability: {anomaly_probability*100}%")
        print(f"  Internal IPs: {self.internal_ips}")
        print()

        start_time = time.time()
        packets_sent = 0
        flows_sent = 0

        # Send template first
        template = self._build_template_flowset()
        packet = self._build_packet([template])
        self.send_packet(packet)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Sent template packet")

        try:
            while time.time() - start_time < duration_seconds:
                all_records = []

                for device_ip in self.internal_ips:
                    # Normal traffic
                    records = self.generate_normal_traffic(device_ip)
                    all_records.extend(records)

                    # Occasional anomaly
                    if random.random() < anomaly_probability:
                        anomaly_type = random.choice(["port_scan", "data_exfil", "c2_beacon", "crypto_mining"])
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] Generating {anomaly_type} anomaly from {device_ip}")
                        records = self.generate_anomalous_traffic(device_ip, anomaly_type)
                        all_records.extend(records)

                # Send in batches
                batch_size = 20
                for i in range(0, len(all_records), batch_size):
                    batch = all_records[i:i+batch_size]
                    data_flowset = self._build_data_flowset(batch)
                    packet = self._build_packet([data_flowset])
                    self.send_packet(packet)
                    packets_sent += 1
                    flows_sent += len(batch)

                # Re-send template periodically
                if packets_sent % 100 == 0:
                    template = self._build_template_flowset()
                    packet = self._build_packet([template])
                    self.send_packet(packet)

                elapsed = int(time.time() - start_time)
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Sent {flows_sent} flows in {packets_sent} packets ({elapsed}s elapsed)")

                # Wait before next batch
                time.sleep(5)

        except KeyboardInterrupt:
            print("\nStopped by user")

        print(f"\nFlow generation complete!")
        print(f"  Total packets: {packets_sent}")
        print(f"  Total flows: {flows_sent}")
        print(f"  Duration: {int(time.time() - start_time)}s")


def main():
    parser = argparse.ArgumentParser(description="NetFlow v9 Test Generator")
    parser.add_argument("--host", default="localhost", help="Collector host")
    parser.add_argument("--port", type=int, default=2055, help="Collector port")
    parser.add_argument("--duration", type=int, default=300, help="Duration in seconds")
    parser.add_argument("--anomaly-rate", type=float, default=0.05, help="Anomaly probability (0-1)")
    parser.add_argument("--site-id", default="60b03fb5-0c97-4c4b-bd6e-79cb0b86db60", help="Site ID")

    args = parser.parse_args()

    generator = NetFlowGenerator(args.host, args.port, args.site_id)
    generator.run(args.duration, args.anomaly_rate)


if __name__ == "__main__":
    main()
