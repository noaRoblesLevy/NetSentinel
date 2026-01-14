# NetSentinel

**Network Security Monitoring Platform for SMEs**

NetSentinel is a self-hosted network anomaly detection platform that uses NetFlow/IPFIX metadata to learn "normal" network behavior and generate explainable alerts when deviations occur.

## Features

- **Flow Collection**: Ingests NetFlow v5/v9/IPFIX from routers, firewalls, and switches
- **Behavioral Baseline**: Learns normal patterns over 7-14 days
- **Anomaly Detection**: Uses Isolation Forest ML to score deviations
- **Explainable Alerts**: Every alert includes "what changed" explanations
- **Device Discovery**: Automatically discovers and profiles network assets
- **Investigation UI**: Modern React dashboard for quick triage
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

- JWT-based authentication with refresh tokens
- Collector-to-backend API key authentication
- No packet payloads captured (metadata only)
- Rate limiting on all endpoints
- Non-root container execution

## License

[Your License Here]

## Contributing

[Contribution guidelines]

## Support

- Documentation: [docs/](docs/)
- Issues: [GitHub Issues](https://github.com/your-org/netsentinel/issues)
