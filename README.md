# NetSentinel

**Network Security Monitoring Platform for SMEs**

NetSentinel is a self-hosted network anomaly detection platform that uses NetFlow/IPFIX metadata to learn "normal" network behavior and generate explainable alerts when deviations occur.

> **Version 1.0** - Production-ready for pilot deployments

## What This Does

- **Detects unusual network behavior** by comparing current traffic patterns to learned baselines
- **Explains alerts in plain language** - "Device X is contacting 150 external destinations instead of the usual 12"
- **Learns automatically** - no manual rule-writing required; just point your NetFlow exporters at it
- **Discovers devices** - builds an inventory of network assets without manual configuration
- **Suppresses noise** - deduplicates alerts, applies persistence rules, and groups related anomalies

## What This Does NOT Do

- **Packet inspection** - only flow metadata is analyzed (src/dst IP, ports, bytes, timestamps)
- **Signature-based detection** - no malware signatures or IOC matching
- **Guaranteed threat detection** - anomaly ≠ malicious; human review is required
- **Replace a SIEM/SOC** - this is a lightweight anomaly detector, not a full security platform
- **Scale to enterprise** - designed for SME networks (up to 200 devices, 20K flows/min)

## Features

- **Flow Collection**: Ingests NetFlow v5/v9/IPFIX from routers, firewalls, and switches
- **Behavioral Baseline**: Learns normal patterns over 7-14 days (configurable)
- **Anomaly Detection**: Uses Isolation Forest ML to score deviations
- **Explainable Alerts**: Every alert includes "what changed" explanations in plain English
- **Device Discovery**: Automatically discovers and profiles network assets
- **Investigation UI**: Modern React dashboard for quick triage
- **Learning Mode**: Visual progress indicator, alerts suppressed until baseline is established
- **Notifications**: Email, Slack, Teams, and webhook integrations

## Architecture

```
Network Device → UDP → Flow Collector (Go) → Backend API (FastAPI)
                                                    ↓
                                           TimescaleDB + Redis
                                                    ↓
                                         Celery Workers (Aggregation, ML, Alerts)
                                                    ↓
                                           React Dashboard
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for detailed architecture documentation.

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Git

### Setup

1. Clone the repository:
```bash
git clone https://github.com/your-org/netsentinel.git
cd netsentinel
```

2. Copy and configure environment:
```bash
cp .env.example .env
# Edit .env with your settings (especially SECRET_KEY and passwords)
```

3. Start all services:
```bash
make setup
# Or manually:
docker-compose up -d
```

4. Access the application:
- **Dashboard**: http://localhost:3000
- **API Docs**: http://localhost:8000/docs
- **Flow Collector**: UDP port 2055

5. Default login:
- Email: `admin@netsentinel.local`
- Password: `changeme` (change immediately!)

### Configure NetFlow Export

Point your network devices to send NetFlow/IPFIX to the collector:

**Cisco IOS:**
```
ip flow-export destination <collector-ip> 2055
ip flow-export version 9
```

**pfSense:**
```
Diagnostics > NetFlow > Destination: <collector-ip>:2055
```

**UniFi:**
```
Settings > Networks > NetFlow > Server: <collector-ip>:2055
```

## Development

### Project Structure

```
netsentinel/
├── collector/      # Go NetFlow/IPFIX collector
├── backend/        # Python FastAPI backend + Celery workers
├── ml/             # ML training and scoring
├── frontend/       # React TypeScript dashboard
├── infra/          # Docker, scripts, configs
├── docs/           # Documentation
└── docker-compose.yml
```

See [docs/FOLDER_STRUCTURE.md](docs/FOLDER_STRUCTURE.md) for detailed structure.

### Running Locally

```bash
# Start all services
make dev

# Run tests
make test

# View logs
make logs

# Run linters
make lint
```

### API Documentation

- Interactive docs: http://localhost:8000/docs
- OpenAPI spec: http://localhost:8000/openapi.json
- Full API reference: [docs/API.md](docs/API.md)

### Database

```bash
# Run migrations
make migrate

# Create new migration
make migrate-new NAME=add_new_column

# Access PostgreSQL shell
make db-shell
```

## Configuration

Key environment variables (see `.env.example` for full list):

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | JWT signing key | (required) |
| `POSTGRES_PASSWORD` | Database password | (required) |
| `COLLECTOR_API_KEY` | Collector auth key | (required) |
| `CORS_ORIGINS` | Allowed frontend origins | localhost:3000 |

## Scale & Performance

MVP targets:
- **Devices**: Up to 200 monitored
- **Flow Rate**: Up to 20,000 flows/minute
- **Storage**: ~175 GB for 30-day retention

For larger deployments, see the scalability section in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Security

- JWT-based authentication with access (60min) and refresh (7 day) tokens
- Collector-to-backend API key authentication
- Role-based access control (admin, analyst, viewer)
- No packet payloads captured (metadata only)
- Rate limiting on all endpoints
- Non-root container execution
- Parameterized queries (SQL injection protection)
- Input validation on all API endpoints

## Known Limitations

1. **Learning period required**: The system needs 7-14 days of baseline data before reliable detection
2. **No real-time alerting**: Anomalies are detected in 5-minute windows with ~2 minute delay
3. **Single-site MVP**: Multi-tenant support exists but is not heavily tested
4. **No HA/clustering**: Single-instance deployment only
5. **English-only**: UI and explanations are in English only
6. **IPv4 focus**: IPv6 support is basic

## Troubleshooting

### No flow data appearing
1. Verify NetFlow is being sent: `tcpdump -i any udp port 2055`
2. Check collector logs: `docker logs netsentinel-collector`
3. Verify collector health: `curl http://localhost:8080/health`

### Alerts not generating
1. Check if site is in learning mode (7 days default)
2. Verify Celery workers are running: `docker logs netsentinel-celery-worker`
3. Confirm anomaly scores exist in the database

### High memory usage
1. Celery workers restart after 100 tasks automatically
2. Reduce `worker_concurrency` in docker-compose.yml
3. Ensure retention policies are active on TimescaleDB

## License

[Your License Here]

## Contributing

[Contribution guidelines]

## Support

- Documentation: [docs/](docs/)
- Issues: [GitHub Issues](https://github.com/your-org/netsentinel/issues)
