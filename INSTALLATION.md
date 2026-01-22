# NetSentinel Installation Guide

This guide covers the installation and deployment of NetSentinel for both development and production environments.

## Prerequisites

### Minimum System Requirements

- **CPU**: 2 cores (4 recommended for production)
- **RAM**: 4 GB (8 GB recommended)
- **Storage**: 50 GB SSD (scales with retention period)
- **OS**: Linux (Ubuntu 22.04 LTS recommended), macOS, or Windows with WSL2

### Required Software

- Docker 24.0+ and Docker Compose v2
- Git

### For Development Only

- Node.js 20+ (for frontend development)
- Python 3.11+ (for backend development)
- Go 1.21+ (for collector development)

## Quick Start (Development)

### 1. Clone the Repository

```bash
git clone https://github.com/noaRoblesLevy/NetSentinel.git
cd NetSentinel
```

### 2. Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Generate secure secrets
echo "SECRET_KEY=$(openssl rand -hex 32)" >> .env
echo "COLLECTOR_API_KEY=$(openssl rand -hex 24)" >> .env
echo "POSTGRES_PASSWORD=$(openssl rand -hex 16)" >> .env
```

Edit `.env` and review all settings, especially:
- `SECRET_KEY` - JWT signing key (minimum 32 characters)
- `POSTGRES_PASSWORD` - Database password
- `COLLECTOR_API_KEY` - API key for collector authentication

### 3. Start Services

```bash
# Using Make (recommended)
make setup

# Or using Docker Compose directly
docker-compose up -d
```

### 4. Create Admin User

```bash
# Using the CLI
docker exec -it netsentinel-backend python -m app.cli create-admin --email admin@yourcompany.com

# Follow the prompts to set password
```

### 5. Access the Application

- **Dashboard**: http://localhost:3000
- **API Documentation**: http://localhost:8000/docs
- **Flow Collector**: UDP port 2055

## Production Deployment

### 1. Server Preparation

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Install Docker Compose plugin
sudo apt install docker-compose-plugin
```

### 2. Clone and Configure

```bash
# Clone repository
git clone https://github.com/noaRoblesLevy/NetSentinel.git
cd NetSentinel

# Create production environment file
cp .env.example .env

# Generate secure production secrets
cat >> .env << EOF
ENVIRONMENT=production
SECRET_KEY=$(openssl rand -hex 32)
COLLECTOR_API_KEY=$(openssl rand -hex 24)
POSTGRES_PASSWORD=$(openssl rand -hex 24)
REDIS_PASSWORD=$(openssl rand -hex 24)
CORS_ORIGINS=https://your-domain.com
EOF
```

### 3. Configure TLS Certificates

#### Option A: Let's Encrypt (Recommended)

```bash
# Install certbot
sudo apt install certbot

# Obtain certificate
sudo certbot certonly --standalone -d your-domain.com

# Copy certificates
sudo cp /etc/letsencrypt/live/your-domain.com/fullchain.pem infra/docker/ssl/
sudo cp /etc/letsencrypt/live/your-domain.com/privkey.pem infra/docker/ssl/
sudo chown $USER:$USER infra/docker/ssl/*.pem
```

#### Option B: Self-Signed (Testing Only)

```bash
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout infra/docker/ssl/privkey.pem \
  -out infra/docker/ssl/fullchain.pem \
  -subj "/CN=your-domain.com"
```

### 4. Deploy Production Stack

```bash
# Start production services
docker compose -f docker-compose.prod.yml up -d

# Check service health
docker compose -f docker-compose.prod.yml ps
```

### 5. Create Admin User

```bash
docker exec -it netsentinel-backend python -m app.cli create-admin --email admin@yourcompany.com
```

### 6. Configure Firewall

```bash
# Allow HTTPS
sudo ufw allow 443/tcp

# Allow NetFlow/IPFIX (adjust as needed)
sudo ufw allow 2055/udp

# Enable firewall
sudo ufw enable
```

## Network Device Configuration

Configure your network devices to send NetFlow/IPFIX to the collector.

### Cisco IOS/IOS-XE

```
! Configure flow exporter
flow exporter NETSENTINEL
 destination <collector-ip>
 transport udp 2055
 source-interface <interface>
 export-protocol netflow-v9

! Configure flow monitor
flow monitor NETSENTINEL-MONITOR
 exporter NETSENTINEL
 record netflow ipv4 original-input

! Apply to interface
interface GigabitEthernet0/0
 ip flow monitor NETSENTINEL-MONITOR input
 ip flow monitor NETSENTINEL-MONITOR output
```

### pfSense

1. Navigate to **Diagnostics > NetFlow**
2. Enable NetFlow on WAN and LAN interfaces
3. Set Destination: `<collector-ip>:2055`
4. Select NetFlow version 9 or IPFIX

### Ubiquiti UniFi

1. Go to **Settings > Networks > Global Network Settings**
2. Enable NetFlow
3. Set Server: `<collector-ip>`
4. Set Port: `2055`

### MikroTik RouterOS

```
/ip traffic-flow
set enabled=yes interfaces=all
/ip traffic-flow target
add dst-address=<collector-ip> port=2055 version=9
```

## Verification

### Check Service Status

```bash
# List all services
docker compose ps

# Check logs
docker compose logs -f backend
docker compose logs -f collector
docker compose logs -f celery-worker
```

### Verify Flow Reception

```bash
# Check collector is receiving flows
curl http://localhost:8080/metrics | grep flows_received

# Check database for flow data
docker exec -it netsentinel-db psql -U netsentinel -c "SELECT COUNT(*) FROM flows_raw WHERE ts_start > NOW() - INTERVAL '1 hour';"
```

### Test API Health

```bash
curl http://localhost:8000/api/v1/health
```

## Troubleshooting

### No Flows Appearing

1. Verify NetFlow is being sent:
   ```bash
   sudo tcpdump -i any udp port 2055 -c 10
   ```

2. Check collector logs:
   ```bash
   docker logs netsentinel-collector
   ```

3. Verify collector health:
   ```bash
   curl http://localhost:8080/health
   ```

### Database Connection Issues

```bash
# Check PostgreSQL status
docker exec netsentinel-db pg_isready

# Check connection from backend
docker exec netsentinel-backend python -c "from app.database import engine; print(engine.url)"
```

### Authentication Errors

1. Verify SECRET_KEY is set and consistent across restarts
2. Check token expiration settings
3. Review auth logs:
   ```bash
   docker logs netsentinel-backend 2>&1 | grep -i auth
   ```

## Maintenance

### Backup Database

```bash
# Backup
docker exec netsentinel-db pg_dump -U netsentinel netsentinel > backup_$(date +%Y%m%d).sql

# Restore
cat backup.sql | docker exec -i netsentinel-db psql -U netsentinel netsentinel
```

### Update Application

```bash
# Pull latest changes
git pull

# Rebuild and restart
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d
```

### View Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f backend

# Last 100 lines
docker compose logs --tail=100 celery-worker
```

## Support

- Documentation: [docs/](docs/)
- Issues: [GitHub Issues](https://github.com/noaRoblesLevy/NetSentinel/issues)
