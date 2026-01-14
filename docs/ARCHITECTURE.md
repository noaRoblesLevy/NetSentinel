# NetSentinel Architecture

## 1. System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              NETWORK INFRASTRUCTURE                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐                            │
│  │  Router  │  │ Firewall │  │  Switch  │  │   AP     │                            │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘                            │
│       │             │             │             │                                   │
│       └─────────────┴──────┬──────┴─────────────┘                                   │
│                            │ NetFlow/IPFIX (UDP 2055)                               │
└────────────────────────────┼────────────────────────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              NETSENTINEL PLATFORM                                    │
│                                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                         INGESTION LAYER                                      │   │
│  │  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐         │   │
│  │  │  Flow Collector │───▶│  Ingestion API  │───▶│  Redis Queue    │         │   │
│  │  │     (Go)        │    │   (FastAPI)     │    │  (Buffer)       │         │   │
│  │  │  UDP:2055       │    │  HTTP:8080      │    │                 │         │   │
│  │  └─────────────────┘    └─────────────────┘    └────────┬────────┘         │   │
│  └─────────────────────────────────────────────────────────┼────────────────────┘   │
│                                                            │                         │
│  ┌─────────────────────────────────────────────────────────┼────────────────────┐   │
│  │                         PROCESSING LAYER                │                     │   │
│  │                                                         ▼                     │   │
│  │  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐          │   │
│  │  │ Celery Worker   │    │  Aggregation    │    │   ML Service    │          │   │
│  │  │ (Flow Writer)   │───▶│  Service        │───▶│ (Scoring)       │          │   │
│  │  │                 │    │  (5-min windows)│    │                 │          │   │
│  │  └─────────────────┘    └─────────────────┘    └────────┬────────┘          │   │
│  └─────────────────────────────────────────────────────────┼────────────────────┘   │
│                                                            │                         │
│  ┌─────────────────────────────────────────────────────────┼────────────────────┐   │
│  │                         ALERTING LAYER                  │                     │   │
│  │                                                         ▼                     │   │
│  │  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐          │   │
│  │  │  Alert Engine   │───▶│  Notification   │───▶│  Email/Slack/   │          │   │
│  │  │                 │    │  Service        │    │  Webhook        │          │   │
│  │  └─────────────────┘    └─────────────────┘    └─────────────────┘          │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                      │
│  ┌──────────────────────────────────────────────────────────────────────────────┐   │
│  │                         DATA LAYER                                            │   │
│  │  ┌─────────────────────────────────────┐    ┌─────────────────────────────┐  │   │
│  │  │         TimescaleDB                 │    │         Redis               │  │   │
│  │  │  ┌─────────────┐ ┌───────────────┐ │    │  • Task Queue               │  │   │
│  │  │  │ flows_raw   │ │ features_5m   │ │    │  • Rate Limiting            │  │   │
│  │  │  │ (hypertable)│ │ (hypertable)  │ │    │  • Session Cache            │  │   │
│  │  │  └─────────────┘ └───────────────┘ │    └─────────────────────────────┘  │   │
│  │  │  ┌─────────────┐ ┌───────────────┐ │                                      │   │
│  │  │  │ anomaly_    │ │ alerts        │ │                                      │   │
│  │  │  │ scores_5m   │ │               │ │                                      │   │
│  │  │  └─────────────┘ └───────────────┘ │                                      │   │
│  │  │  ┌─────────────┐ ┌───────────────┐ │                                      │   │
│  │  │  │ assets      │ │ rules         │ │                                      │   │
│  │  │  └─────────────┘ └───────────────┘ │                                      │   │
│  │  └─────────────────────────────────────┘                                      │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                      │
│  ┌──────────────────────────────────────────────────────────────────────────────┐   │
│  │                         PRESENTATION LAYER                                    │   │
│  │  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐          │   │
│  │  │  React Frontend │◀──▶│  FastAPI        │◀──▶│  Auth Service   │          │   │
│  │  │  (Dashboard)    │    │  (REST API)     │    │  (JWT)          │          │   │
│  │  │  Port: 3000     │    │  Port: 8000     │    │                 │          │   │
│  │  └─────────────────┘    └─────────────────┘    └─────────────────┘          │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

## 2. Component Responsibilities

### 2.1 Flow Collector (Go)
**Location:** `collector/`

**Responsibilities:**
- Listen on UDP port 2055 for NetFlow v5/v9/IPFIX packets
- Parse and validate flow records
- Normalize to internal schema
- Batch and forward to Ingestion API via HTTP
- Handle packet loss and exporter resets gracefully
- Track collector metrics (flows/sec, parse errors)

**Why Go:**
- Excellent UDP/network performance
- Low memory footprint
- Easy cross-compilation for deployment

### 2.2 Backend API (FastAPI)
**Location:** `backend/`

**Responsibilities:**
- REST API for frontend and integrations
- Flow ingestion endpoint (receives from collector)
- CRUD operations for assets, alerts, rules
- Authentication and authorization (JWT)
- Request validation and rate limiting
- WebSocket for real-time dashboard updates (future)

### 2.3 Celery Workers
**Location:** `backend/workers/`

**Responsibilities:**
- **Flow Writer Worker:** Batch insert flows from Redis queue to TimescaleDB
- **Aggregation Worker:** Run every 5 minutes, compute feature vectors
- **ML Scoring Worker:** Score feature vectors against trained model
- **Alert Worker:** Generate alerts from anomaly scores
- **Notification Worker:** Send email/Slack/webhook notifications

### 2.4 ML Service
**Location:** `ml/`

**Responsibilities:**
- Train Isolation Forest models per site
- Store model artifacts with versioning
- Score incoming feature vectors
- Generate feature importance for explainability
- Handle baseline learning mode (first 7-14 days)

### 2.5 React Frontend
**Location:** `frontend/`

**Responsibilities:**
- Dashboard with network overview
- Alert list and detail views
- Device profiles and behavior timelines
- Investigation workflows
- Rules and settings management
- Responsive design for desktop/tablet

## 3. Data Flow (Detailed)

```
FLOW LIFECYCLE:
═══════════════

Step 1: Collection
──────────────────
Router/Firewall ──UDP──▶ Flow Collector (Go)
                              │
                              ▼
                         Parse NetFlow/IPFIX
                         Normalize fields
                         Validate checksums
                              │
                              ▼
                         Batch (100 flows or 1 sec)

Step 2: Ingestion
─────────────────
Flow Collector ──HTTP POST──▶ /api/v1/flows/ingest
                                    │
                                    ▼
                              Validate batch
                              Enrich (is_internal)
                              Push to Redis Queue
                                    │
                                    ▼
                              Return 202 Accepted

Step 3: Storage
───────────────
Celery Worker ◀── Redis Queue
      │
      ▼
Batch INSERT to flows_raw (TimescaleDB)
      │
      ▼
Update assets table (first_seen, last_seen)

Step 4: Aggregation (Every 5 Minutes)
─────────────────────────────────────
Celery Beat triggers aggregation_task
      │
      ▼
Query flows_raw for last 5-min window
      │
      ▼
GROUP BY asset_id, compute features:
  • flows_in, flows_out
  • bytes_in, bytes_out
  • unique_dst_ips, unique_dst_ports
  • port_entropy, dst_ip_entropy
  • internal_external_ratio
      │
      ▼
INSERT to features_5m

Step 5: ML Scoring
──────────────────
After aggregation completes:
      │
      ▼
Load trained Isolation Forest model
      │
      ▼
Score each feature vector
      │
      ▼
Compute feature contributions (SHAP-like)
      │
      ▼
INSERT to anomaly_scores_5m

Step 6: Alert Generation
────────────────────────
For each score > threshold:
      │
      ▼
Check suppression rules
      │
      ▼
Check deduplication (same device + similar anomaly)
      │
      ▼
Generate explanation:
  "unique_dst_ips increased 340% vs baseline"
  "bytes_out 8x normal for this hour"
      │
      ▼
INSERT to alerts

Step 7: Notification
────────────────────
New alert created:
      │
      ▼
Check notification preferences
      │
      ▼
Send via configured channels:
  • Email (SMTP)
  • Slack (webhook)
  • Generic webhook
```

## 4. MVP Scale Calculations

**Target:** 200 devices, 20,000 flows/minute

```
Flows:
  • 20,000 flows/min = 333 flows/sec
  • Flow record size: ~200 bytes
  • Raw data rate: ~67 KB/sec = ~5.7 GB/day

Storage (30-day retention for raw flows):
  • Raw flows: 5.7 GB × 30 = ~170 GB
  • Features (5-min windows): 200 devices × 288 windows/day × 30 days × 500 bytes = ~860 MB
  • Scores: ~860 MB (same cardinality as features)
  • Total: ~175 GB (easily handled by single Postgres instance)

Processing:
  • Aggregation: 100k flows per 5-min window
  • Aggregation time: < 10 seconds with proper indexes
  • ML scoring: 200 devices × 1ms = 200ms per window

Memory:
  • Collector: ~50 MB
  • Backend: ~200 MB
  • Worker: ~300 MB (ML model in memory)
  • Redis: ~100 MB
  • Postgres: ~1 GB (shared_buffers)
  • Total: ~2 GB RAM minimum
```

## 5. Technology Choices Rationale

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Collector | Go | Best UDP performance, low memory, easy deployment |
| Backend | FastAPI | Async support, auto OpenAPI docs, Python ML ecosystem |
| Task Queue | Celery + Redis | Battle-tested, easy debugging, good monitoring |
| Database | TimescaleDB | Time-series optimized Postgres, familiar SQL, hypertables |
| ML | scikit-learn | Isolation Forest out-of-box, simple, sufficient for MVP |
| Frontend | React + TypeScript | Strong ecosystem, type safety, shadcn/ui components |
| Deployment | Docker Compose | Simple local dev, easy to upgrade to K8s later |

## 6. Security Considerations

- **Authentication:** JWT tokens with refresh rotation
- **API Security:** Rate limiting, input validation, CORS
- **Collector Auth:** API key for collector → backend communication
- **Data Privacy:** No packet payloads, metadata only
- **Network:** Internal services not exposed, only frontend + API
- **Secrets:** Environment variables, never in code

## 7. Future Scalability Path

```
MVP (Current):
  Single instance, Docker Compose
  ↓
Growth (1000+ devices):
  • Split collector to dedicated host
  • Add read replica for Postgres
  • Horizontal scale workers
  ↓
Scale (10k+ devices):
  • Migrate flows_raw to ClickHouse
  • Add Kafka for flow ingestion
  • Kubernetes deployment
  • Multi-region support
```
