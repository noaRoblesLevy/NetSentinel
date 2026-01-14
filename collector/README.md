# NetSentinel Flow Collector

High-performance UDP collector for NetFlow v9 and IPFIX flow records.

## Features

- **Protocol Support**: NetFlow v9 and IPFIX (RFC 7011)
- **High Throughput**: Handles 20k+ flows/minute on modest hardware
- **Backpressure Handling**: Graceful degradation under load
- **Batching**: Configurable batch size and flush intervals
- **Retry Logic**: Exponential backoff on backend failures
- **Multiple Backends**: HTTP API or direct PostgreSQL output
- **Metrics**: Prometheus-compatible metrics endpoint
- **Health Checks**: Kubernetes-ready health and readiness probes

## Architecture

```
UDP Packets (NetFlow/IPFIX)
         │
         ▼
    ┌─────────────┐
    │ UDP Server  │  Receives packets on port 2055
    └──────┬──────┘
           │
           ▼
    ┌─────────────┐
    │   Parser    │  NetFlow v9 / IPFIX parsing
    └──────┬──────┘
           │
           ▼
    ┌─────────────┐
    │  Normalizer │  Converts to canonical flow.Record
    └──────┬──────┘
           │
           ▼
    ┌─────────────┐
    │ Input Queue │  Bounded channel (backpressure)
    └──────┬──────┘
           │
           ▼
    ┌─────────────┐
    │   Batcher   │  Collects records into batches
    └──────┬──────┘
           │
           ▼
    ┌─────────────┐
    │   Sender    │  HTTP or PostgreSQL with retry
    └─────────────┘
```

## Configuration

All configuration is via environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `COLLECTOR_UDP_PORT` | UDP port to listen on | `2055` |
| `COLLECTOR_UDP_BUFFER_SIZE` | UDP socket buffer size | `65535` |
| `COLLECTOR_BATCH_SIZE` | Flows per batch | `100` |
| `COLLECTOR_FLUSH_INTERVAL` | Max time before flush | `1s` |
| `COLLECTOR_QUEUE_SIZE` | Input queue capacity | `10000` |
| `COLLECTOR_MAX_RETRIES` | Max send retry attempts | `5` |
| `COLLECTOR_RETRY_BACKOFF` | Initial retry delay | `100ms` |
| `COLLECTOR_MAX_RETRY_BACKOFF` | Max retry delay | `30s` |
| `COLLECTOR_OUTPUT_MODE` | `http` or `postgres` | `http` |
| `BACKEND_URL` | Backend API URL (http mode) | `http://localhost:8000` |
| `COLLECTOR_API_KEY` | API key for backend auth | `` |
| `DATABASE_URL` | PostgreSQL URL (postgres mode) | `` |
| `DEFAULT_SITE_ID` | Default site ID for flows | `` |
| `COLLECTOR_HEALTH_PORT` | HTTP health server port | `8080` |
| `LOG_LEVEL` | Log level (debug/info/warn/error) | `info` |
| `LOG_JSON` | JSON log format | `false` |

## Running

### With Docker

```bash
# Build the image
docker build -t netsentinel-collector .

# Run with HTTP backend
docker run -d \
  --name collector \
  -p 2055:2055/udp \
  -p 8080:8080 \
  -e BACKEND_URL=http://backend:8000 \
  -e COLLECTOR_API_KEY=your-api-key \
  -e DEFAULT_SITE_ID=your-site-id \
  netsentinel-collector

# Run with PostgreSQL backend
docker run -d \
  --name collector \
  -p 2055:2055/udp \
  -p 8080:8080 \
  -e COLLECTOR_OUTPUT_MODE=postgres \
  -e DATABASE_URL=postgres://user:pass@host:5432/netsentinel \
  -e DEFAULT_SITE_ID=your-site-id \
  netsentinel-collector
```

### With Docker Compose

The collector is included in the main `docker-compose.yml`:

```bash
# From project root
docker-compose up -d collector
```

### Locally (Development)

```bash
# Install dependencies
go mod download

# Run tests
go test -v ./...

# Build
go build -o collector ./cmd/collector

# Run
COLLECTOR_OUTPUT_MODE=http \
BACKEND_URL=http://localhost:8000 \
./collector
```

## Endpoints

### Health Check

```bash
curl http://localhost:8080/health
```

Response:
```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00Z",
  "uptime": "1h30m45s"
}
```

### Readiness Check

```bash
curl http://localhost:8080/ready
```

### Detailed Stats

```bash
curl http://localhost:8080/stats
```

Response:
```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "uptime": "1h30m45s",
  "udp": {
    "packets_received": 125000,
    "packets_invalid": 12,
    "bytes_received": 18750000,
    "flows_parsed": 450000,
    "parse_errors": 5,
    "nf_templates": 3,
    "ipfix_templates": 2
  },
  "sender": {
    "flows_received": 450000,
    "flows_sent": 449500,
    "flows_dropped": 500,
    "batches_sent": 4495,
    "batches_failed": 2,
    "retry_count": 15,
    "queue_depth": 150
  },
  "runtime": {
    "goroutines": 8,
    "heap_alloc": 12582912,
    "gc_cycles": 45
  }
}
```

### Prometheus Metrics

```bash
curl http://localhost:8080/metrics
```

Available metrics:
- `netsentinel_collector_packets_total` - Total UDP packets received
- `netsentinel_collector_flows_total` - Total flow records processed
- `netsentinel_collector_flows_dropped_total` - Flows dropped due to backpressure
- `netsentinel_collector_batches_sent_total` - Batches successfully sent
- `netsentinel_collector_batches_failed_total` - Batches that failed to send
- `netsentinel_collector_queue_depth` - Current input queue depth
- `netsentinel_collector_parse_errors_total` - Packet parse errors

## Testing with Flow Generator

You can test the collector using `nflow-generator`:

```bash
# Generate test NetFlow v9 data
docker run --rm --network host networkstatic/nflow-generator \
  -t localhost -p 2055 -c 1000 -s 5
```

Or using `softflowd` on a Linux machine:

```bash
# Capture and export flows from eth0
softflowd -i eth0 -n localhost:2055 -v 9
```

## Canonical Flow Record

All flows are normalized to this structure:

```json
{
  "ts_start": "2024-01-15T10:30:00Z",
  "ts_end": "2024-01-15T10:30:05Z",
  "duration_ms": 5000,
  "src_ip": "192.168.1.100",
  "dst_ip": "8.8.8.8",
  "src_port": 54321,
  "dst_port": 443,
  "protocol": 6,
  "bytes": 15000,
  "packets": 12,
  "tcp_flags": 24,
  "exporter_ip": "10.0.0.1",
  "exporter_id": "10.0.0.1:12345",
  "site_id": "site-abc",
  "source_format": "netflow_v9"
}
```

## Troubleshooting

### No flows being received

1. Check firewall allows UDP 2055
2. Verify exporter is sending to correct IP/port
3. Check logs: `docker logs collector`
4. Verify with tcpdump: `tcpdump -i any udp port 2055`

### High drop rate

1. Increase `COLLECTOR_QUEUE_SIZE`
2. Increase `COLLECTOR_BATCH_SIZE`
3. Check backend is healthy
4. Monitor `/stats` endpoint for queue depth

### Parse errors

1. Check `LOG_LEVEL=debug` for details
2. Verify exporter is sending v9 or IPFIX (not v5)
3. Template packets may need to be resent after collector restart

## License

Part of the NetSentinel project.
