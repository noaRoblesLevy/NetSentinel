# NetSentinel API Documentation

Base URL: `http://localhost:8000/api/v1`

## Authentication

All endpoints (except `/auth/login`) require a JWT Bearer token.

```
Authorization: Bearer <token>
```

---

## Auth Endpoints

### POST /auth/login
Authenticate and receive JWT tokens.

**Request:**
```json
{
  "email": "admin@netsentinel.local",
  "password": "your-password"
}
```

**Response (200):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 3600,
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "admin@netsentinel.local",
    "full_name": "System Admin",
    "role": "admin"
  }
}
```

### POST /auth/refresh
Refresh access token.

**Request:**
```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIs..."
}
```

**Response (200):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "expires_in": 3600
}
```

---

## Flow Endpoints

### POST /flows/ingest
Receive flow records from collector. Used internally by the Go collector.

**Headers:**
```
X-Collector-Key: <collector-api-key>
Content-Type: application/json
```

**Request:**
```json
{
  "site_id": "550e8400-e29b-41d4-a716-446655440000",
  "exporter_id": "192.168.1.1",
  "flows": [
    {
      "ts_start": "2024-01-15T10:30:00Z",
      "ts_end": "2024-01-15T10:30:05Z",
      "src_ip": "192.168.1.100",
      "dst_ip": "8.8.8.8",
      "src_port": 52431,
      "dst_port": 443,
      "protocol": 6,
      "bytes": 15420,
      "packets": 12,
      "tcp_flags": 24
    },
    {
      "ts_start": "2024-01-15T10:30:01Z",
      "ts_end": "2024-01-15T10:30:03Z",
      "src_ip": "192.168.1.101",
      "dst_ip": "192.168.1.10",
      "src_port": 49152,
      "dst_port": 445,
      "protocol": 6,
      "bytes": 2048,
      "packets": 4,
      "tcp_flags": 16
    }
  ]
}
```

**Response (202 Accepted):**
```json
{
  "status": "accepted",
  "flows_received": 2,
  "batch_id": "batch_20240115_103000_abc123"
}
```

### GET /flows/stats
Get flow ingestion statistics.

**Query Parameters:**
- `site_id` (required): UUID
- `start_time` (optional): ISO timestamp, default last hour
- `end_time` (optional): ISO timestamp

**Response (200):**
```json
{
  "site_id": "550e8400-e29b-41d4-a716-446655440000",
  "time_range": {
    "start": "2024-01-15T09:30:00Z",
    "end": "2024-01-15T10:30:00Z"
  },
  "stats": {
    "total_flows": 125000,
    "total_bytes": 1584000000,
    "total_packets": 892000,
    "flows_per_minute": 2083,
    "unique_internal_ips": 145,
    "unique_external_ips": 3420
  }
}
```

---

## Asset Endpoints

### GET /assets
List discovered assets.

**Query Parameters:**
- `site_id` (required): UUID
- `role_tag` (optional): server|workstation|iot|infrastructure|unknown
- `search` (optional): Search by IP or hostname
- `sort_by` (optional): last_seen|first_seen|ip, default: last_seen
- `order` (optional): asc|desc, default: desc
- `page` (optional): int, default: 1
- `page_size` (optional): int, default: 50, max: 200

**Response (200):**
```json
{
  "items": [
    {
      "id": "660e8400-e29b-41d4-a716-446655440001",
      "site_id": "550e8400-e29b-41d4-a716-446655440000",
      "ip": "192.168.1.100",
      "hostname": "workstation-jdoe",
      "role_tag": "workstation",
      "custom_name": "John's Laptop",
      "subnet_label": "Workstations",
      "first_seen": "2024-01-01T08:00:00Z",
      "last_seen": "2024-01-15T10:25:00Z",
      "is_monitored": true,
      "stats": {
        "avg_daily_flows": 12500,
        "avg_daily_bytes": 850000000,
        "anomaly_count_7d": 2
      }
    },
    {
      "id": "660e8400-e29b-41d4-a716-446655440002",
      "site_id": "550e8400-e29b-41d4-a716-446655440000",
      "ip": "192.168.1.10",
      "hostname": "dc01.internal.local",
      "role_tag": "server",
      "custom_name": "Domain Controller",
      "subnet_label": "Servers",
      "first_seen": "2024-01-01T00:00:00Z",
      "last_seen": "2024-01-15T10:30:00Z",
      "is_monitored": true,
      "stats": {
        "avg_daily_flows": 45000,
        "avg_daily_bytes": 2500000000,
        "anomaly_count_7d": 0
      }
    }
  ],
  "total": 145,
  "page": 1,
  "page_size": 50,
  "pages": 3
}
```

### GET /assets/{asset_id}
Get detailed asset information.

**Response (200):**
```json
{
  "id": "660e8400-e29b-41d4-a716-446655440001",
  "site_id": "550e8400-e29b-41d4-a716-446655440000",
  "ip": "192.168.1.100",
  "hostname": "workstation-jdoe",
  "mac_address": "00:1A:2B:3C:4D:5E",
  "role_tag": "workstation",
  "custom_name": "John's Laptop",
  "subnet_label": "Workstations",
  "first_seen": "2024-01-01T08:00:00Z",
  "last_seen": "2024-01-15T10:25:00Z",
  "is_monitored": true,
  "notes": "Primary workstation for John Doe, Finance dept",

  "behavior_profile": {
    "typical_active_hours": [8, 9, 10, 11, 12, 13, 14, 15, 16, 17],
    "avg_daily_flows": 12500,
    "avg_daily_bytes": 850000000,
    "top_destinations": [
      {"ip": "13.107.42.14", "hostname": "outlook.office365.com", "percentage": 35},
      {"ip": "192.168.1.10", "hostname": "dc01.internal.local", "percentage": 25},
      {"ip": "8.8.8.8", "hostname": "dns.google", "percentage": 15}
    ],
    "top_services": [
      {"port": 443, "name": "HTTPS", "percentage": 72},
      {"port": 445, "name": "SMB", "percentage": 15},
      {"port": 53, "name": "DNS", "percentage": 8}
    ],
    "internal_external_ratio": 0.35
  },

  "recent_anomalies": [
    {
      "id": "770e8400-e29b-41d4-a716-446655440001",
      "timestamp": "2024-01-14T02:30:00Z",
      "score": 0.87,
      "title": "Unusual external connection volume"
    }
  ],

  "alerts_summary": {
    "total_7d": 2,
    "open": 1,
    "high_severity": 0
  }
}
```

### PATCH /assets/{asset_id}
Update asset details.

**Request:**
```json
{
  "custom_name": "John's Laptop - Finance",
  "role_tag": "workstation",
  "is_monitored": true,
  "notes": "Updated notes"
}
```

**Response (200):**
```json
{
  "id": "660e8400-e29b-41d4-a716-446655440001",
  "custom_name": "John's Laptop - Finance",
  "role_tag": "workstation",
  "is_monitored": true,
  "notes": "Updated notes",
  "updated_at": "2024-01-15T10:35:00Z"
}
```

### GET /assets/{asset_id}/timeline
Get behavior timeline for an asset.

**Query Parameters:**
- `start_time` (optional): ISO timestamp, default: 24 hours ago
- `end_time` (optional): ISO timestamp, default: now
- `resolution` (optional): 5m|15m|1h, default: 5m

**Response (200):**
```json
{
  "asset_id": "660e8400-e29b-41d4-a716-446655440001",
  "resolution": "5m",
  "time_range": {
    "start": "2024-01-14T10:30:00Z",
    "end": "2024-01-15T10:30:00Z"
  },
  "timeline": [
    {
      "window_start": "2024-01-15T10:25:00Z",
      "flows_in": 45,
      "flows_out": 120,
      "bytes_in": 125000,
      "bytes_out": 850000,
      "unique_dst_ips": 8,
      "unique_dst_ports": 4,
      "anomaly_score": 0.12,
      "is_anomaly": false
    },
    {
      "window_start": "2024-01-15T10:20:00Z",
      "flows_in": 52,
      "flows_out": 98,
      "bytes_in": 145000,
      "bytes_out": 720000,
      "unique_dst_ips": 6,
      "unique_dst_ports": 3,
      "anomaly_score": 0.08,
      "is_anomaly": false
    }
  ],
  "baseline": {
    "avg_flows_out": 95,
    "avg_bytes_out": 680000,
    "avg_unique_dst_ips": 5
  }
}
```

---

## Alert Endpoints

### GET /alerts
List alerts with filtering and pagination.

**Query Parameters:**
- `site_id` (required): UUID
- `status` (optional): open|acknowledged|investigating|resolved|false_positive
- `severity` (optional): low|medium|high|critical
- `asset_id` (optional): Filter by specific asset
- `start_time` (optional): ISO timestamp
- `end_time` (optional): ISO timestamp
- `sort_by` (optional): created_at|severity|score, default: created_at
- `order` (optional): asc|desc, default: desc
- `page` (optional): int, default: 1
- `page_size` (optional): int, default: 50

**Response (200):**
```json
{
  "items": [
    {
      "id": "770e8400-e29b-41d4-a716-446655440001",
      "site_id": "550e8400-e29b-41d4-a716-446655440000",
      "asset_id": "660e8400-e29b-41d4-a716-446655440001",
      "alert_type": "anomaly_detection",
      "severity": "high",
      "status": "open",
      "title": "Unusual external connection pattern detected",
      "peak_score": 0.92,
      "start_time": "2024-01-15T02:30:00Z",
      "end_time": "2024-01-15T02:45:00Z",
      "created_at": "2024-01-15T02:35:00Z",
      "asset": {
        "ip": "192.168.1.100",
        "hostname": "workstation-jdoe",
        "custom_name": "John's Laptop"
      },
      "explanation_summary": "unique_dst_ips increased 340% vs baseline"
    },
    {
      "id": "770e8400-e29b-41d4-a716-446655440002",
      "site_id": "550e8400-e29b-41d4-a716-446655440000",
      "asset_id": "660e8400-e29b-41d4-a716-446655440003",
      "alert_type": "anomaly_detection",
      "severity": "medium",
      "status": "acknowledged",
      "title": "Elevated data transfer volume",
      "peak_score": 0.78,
      "start_time": "2024-01-15T01:15:00Z",
      "end_time": null,
      "created_at": "2024-01-15T01:20:00Z",
      "asset": {
        "ip": "192.168.1.55",
        "hostname": "server-backup",
        "custom_name": "Backup Server"
      },
      "explanation_summary": "bytes_out 5.2x above normal for this hour"
    }
  ],
  "total": 24,
  "page": 1,
  "page_size": 50,
  "pages": 1,
  "summary": {
    "open": 12,
    "acknowledged": 5,
    "investigating": 3,
    "resolved": 4,
    "by_severity": {
      "critical": 1,
      "high": 5,
      "medium": 12,
      "low": 6
    }
  }
}
```

### GET /alerts/{alert_id}
Get detailed alert information.

**Response (200):**
```json
{
  "id": "770e8400-e29b-41d4-a716-446655440001",
  "site_id": "550e8400-e29b-41d4-a716-446655440000",
  "asset_id": "660e8400-e29b-41d4-a716-446655440001",

  "alert_type": "anomaly_detection",
  "severity": "high",
  "status": "open",

  "title": "Unusual external connection pattern detected",
  "description": "The device established connections to an unusually high number of external IP addresses during off-hours, with behavior inconsistent with its historical baseline.",

  "peak_score": 0.92,
  "avg_score": 0.85,

  "start_time": "2024-01-15T02:30:00Z",
  "end_time": "2024-01-15T02:45:00Z",
  "duration_minutes": 15,

  "asset": {
    "id": "660e8400-e29b-41d4-a716-446655440001",
    "ip": "192.168.1.100",
    "hostname": "workstation-jdoe",
    "custom_name": "John's Laptop",
    "role_tag": "workstation"
  },

  "explanation": {
    "summary": "Multiple behavioral indicators suggest unusual network activity",
    "contributing_factors": [
      {
        "feature": "unique_dst_ips",
        "description": "Unique external destinations",
        "current_value": 47,
        "baseline_value": 11,
        "change_percentage": 327,
        "contribution_score": 0.35,
        "interpretation": "Connected to 4x more external IPs than normal"
      },
      {
        "feature": "bytes_out",
        "description": "Outbound data volume",
        "current_value": 125000000,
        "baseline_value": 15000000,
        "change_percentage": 733,
        "contribution_score": 0.28,
        "interpretation": "Transferred 8x more data than typical"
      },
      {
        "feature": "hour_deviation",
        "description": "Time of activity",
        "current_value": "02:30",
        "baseline_value": "09:00-17:00",
        "change_percentage": null,
        "contribution_score": 0.22,
        "interpretation": "Activity occurred outside normal working hours"
      },
      {
        "feature": "dst_port_entropy",
        "description": "Port diversity",
        "current_value": 3.2,
        "baseline_value": 1.8,
        "change_percentage": 78,
        "contribution_score": 0.15,
        "interpretation": "Connected to a wider variety of ports than usual"
      }
    ],
    "new_destinations": [
      {"ip": "45.33.32.156", "first_seen": "2024-01-15T02:31:00Z", "bytes": 5200000},
      {"ip": "185.199.108.153", "first_seen": "2024-01-15T02:32:00Z", "bytes": 3100000},
      {"ip": "104.21.234.56", "first_seen": "2024-01-15T02:35:00Z", "bytes": 2800000}
    ]
  },

  "suggested_actions": [
    "Review the list of new external destinations",
    "Check if the user was working remotely during this time",
    "Verify no unauthorized software was installed",
    "Compare with other devices in the same subnet"
  ],

  "related_alerts": [
    {
      "id": "770e8400-e29b-41d4-a716-446655440000",
      "title": "Minor traffic spike",
      "created_at": "2024-01-14T22:00:00Z",
      "status": "resolved"
    }
  ],

  "timeline": [
    {
      "window_start": "2024-01-15T02:30:00Z",
      "anomaly_score": 0.85,
      "top_feature": "unique_dst_ips"
    },
    {
      "window_start": "2024-01-15T02:35:00Z",
      "anomaly_score": 0.92,
      "top_feature": "bytes_out"
    },
    {
      "window_start": "2024-01-15T02:40:00Z",
      "anomaly_score": 0.78,
      "top_feature": "unique_dst_ips"
    }
  ],

  "created_at": "2024-01-15T02:35:00Z",
  "updated_at": "2024-01-15T02:35:00Z",
  "notified_at": "2024-01-15T02:36:00Z",
  "notification_channels": ["email", "slack"]
}
```

### PATCH /alerts/{alert_id}
Update alert status.

**Request:**
```json
{
  "status": "acknowledged",
  "resolution_notes": "Investigating - appears to be scheduled backup job"
}
```

**Response (200):**
```json
{
  "id": "770e8400-e29b-41d4-a716-446655440001",
  "status": "acknowledged",
  "resolution_notes": "Investigating - appears to be scheduled backup job",
  "status_changed_at": "2024-01-15T10:45:00Z",
  "status_changed_by": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "admin@netsentinel.local"
  },
  "updated_at": "2024-01-15T10:45:00Z"
}
```

### POST /alerts/{alert_id}/mark-expected
Create a suppression rule from this alert.

**Request:**
```json
{
  "rule_name": "Backup server nightly transfers",
  "expires_in_days": 30,
  "apply_to_similar": true
}
```

**Response (201):**
```json
{
  "alert_updated": {
    "id": "770e8400-e29b-41d4-a716-446655440001",
    "status": "false_positive"
  },
  "rule_created": {
    "id": "880e8400-e29b-41d4-a716-446655440001",
    "name": "Backup server nightly transfers",
    "rule_type": "suppress",
    "conditions": {
      "asset_id": "660e8400-e29b-41d4-a716-446655440001",
      "hour_range": [1, 5],
      "alert_type": "anomaly_detection"
    },
    "expires_at": "2024-02-14T10:45:00Z"
  }
}
```

---

## Rules Endpoints

### GET /rules
List suppression and allowlist rules.

**Query Parameters:**
- `site_id` (required): UUID
- `rule_type` (optional): allowlist|suppress|threshold|custom
- `is_enabled` (optional): boolean

**Response (200):**
```json
{
  "items": [
    {
      "id": "880e8400-e29b-41d4-a716-446655440001",
      "site_id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "Backup server nightly transfers",
      "description": "Suppress alerts for backup server during nightly backup window",
      "rule_type": "suppress",
      "conditions": {
        "asset_id": "660e8400-e29b-41d4-a716-446655440003",
        "hour_range": [1, 5]
      },
      "action": "ignore",
      "is_enabled": true,
      "times_matched": 45,
      "last_matched_at": "2024-01-15T03:00:00Z",
      "expires_at": "2024-02-14T10:45:00Z",
      "created_at": "2024-01-10T12:00:00Z"
    },
    {
      "id": "880e8400-e29b-41d4-a716-446655440002",
      "site_id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "Microsoft 365 IPs",
      "description": "Allow connections to Microsoft 365 infrastructure",
      "rule_type": "allowlist",
      "conditions": {
        "dst_ip_ranges": ["13.107.0.0/16", "52.96.0.0/14", "40.104.0.0/15"]
      },
      "action": "ignore",
      "is_enabled": true,
      "times_matched": 12500,
      "last_matched_at": "2024-01-15T10:30:00Z",
      "expires_at": null,
      "created_at": "2024-01-01T00:00:00Z"
    }
  ],
  "total": 8,
  "page": 1,
  "page_size": 50
}
```

### POST /rules
Create a new rule.

**Request:**
```json
{
  "name": "Ignore IoT devices high entropy",
  "description": "IoT devices often connect to many different cloud services",
  "rule_type": "suppress",
  "conditions": {
    "asset_role": "iot",
    "triggered_by_features": ["dst_ip_entropy", "unique_dst_ips"]
  },
  "action": "reduce_severity",
  "action_params": {
    "reduce_to": "low"
  },
  "is_enabled": true,
  "expires_at": null
}
```

**Response (201):**
```json
{
  "id": "880e8400-e29b-41d4-a716-446655440003",
  "site_id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Ignore IoT devices high entropy",
  "description": "IoT devices often connect to many different cloud services",
  "rule_type": "suppress",
  "conditions": {
    "asset_role": "iot",
    "triggered_by_features": ["dst_ip_entropy", "unique_dst_ips"]
  },
  "action": "reduce_severity",
  "action_params": {
    "reduce_to": "low"
  },
  "is_enabled": true,
  "times_matched": 0,
  "expires_at": null,
  "created_at": "2024-01-15T10:50:00Z",
  "created_by": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "admin@netsentinel.local"
  }
}
```

### PATCH /rules/{rule_id}
Update a rule.

**Request:**
```json
{
  "is_enabled": false
}
```

**Response (200):**
```json
{
  "id": "880e8400-e29b-41d4-a716-446655440003",
  "is_enabled": false,
  "updated_at": "2024-01-15T11:00:00Z"
}
```

### DELETE /rules/{rule_id}
Delete a rule.

**Response (204):** No content

---

## Dashboard Endpoints

### GET /dashboard/overview
Get dashboard overview statistics.

**Query Parameters:**
- `site_id` (required): UUID

**Response (200):**
```json
{
  "site_id": "550e8400-e29b-41d4-a716-446655440000",
  "site_status": "active",
  "generated_at": "2024-01-15T10:55:00Z",

  "alerts": {
    "open_total": 12,
    "open_high": 3,
    "open_critical": 1,
    "last_24h": 8,
    "trend": "+15%"
  },

  "devices": {
    "total_monitored": 145,
    "active_last_hour": 98,
    "new_last_24h": 2,
    "top_anomalous": [
      {
        "id": "660e8400-e29b-41d4-a716-446655440001",
        "ip": "192.168.1.100",
        "custom_name": "John's Laptop",
        "anomaly_score": 0.87,
        "open_alerts": 2
      },
      {
        "id": "660e8400-e29b-41d4-a716-446655440005",
        "ip": "192.168.1.203",
        "custom_name": null,
        "anomaly_score": 0.72,
        "open_alerts": 1
      }
    ]
  },

  "traffic": {
    "flows_last_hour": 125000,
    "bytes_last_hour": 8500000000,
    "trend_flows": "+5%",
    "trend_bytes": "+12%"
  },

  "model_status": {
    "status": "active",
    "last_trained": "2024-01-14T00:00:00Z",
    "next_training": "2024-01-21T00:00:00Z",
    "baseline_days": 14
  }
}
```

### GET /dashboard/traffic-chart
Get traffic time-series for charts.

**Query Parameters:**
- `site_id` (required): UUID
- `start_time` (optional): ISO timestamp, default: 24h ago
- `end_time` (optional): ISO timestamp
- `resolution` (optional): 5m|15m|1h|1d, default: 1h

**Response (200):**
```json
{
  "site_id": "550e8400-e29b-41d4-a716-446655440000",
  "resolution": "1h",
  "time_range": {
    "start": "2024-01-14T11:00:00Z",
    "end": "2024-01-15T11:00:00Z"
  },
  "data": [
    {
      "timestamp": "2024-01-15T10:00:00Z",
      "flows": 125000,
      "bytes_in": 4200000000,
      "bytes_out": 4300000000,
      "unique_internal_ips": 98,
      "unique_external_ips": 3420,
      "anomaly_count": 2
    },
    {
      "timestamp": "2024-01-15T09:00:00Z",
      "flows": 118000,
      "bytes_in": 3900000000,
      "bytes_out": 4100000000,
      "unique_internal_ips": 95,
      "unique_external_ips": 3250,
      "anomaly_count": 1
    }
  ]
}
```

### GET /dashboard/recent-activity
Get recent activity feed.

**Query Parameters:**
- `site_id` (required): UUID
- `limit` (optional): int, default: 20

**Response (200):**
```json
{
  "site_id": "550e8400-e29b-41d4-a716-446655440000",
  "activities": [
    {
      "type": "alert_created",
      "timestamp": "2024-01-15T10:35:00Z",
      "title": "New high-severity alert",
      "description": "Unusual external connection pattern on workstation-jdoe",
      "resource_id": "770e8400-e29b-41d4-a716-446655440001",
      "severity": "high"
    },
    {
      "type": "device_discovered",
      "timestamp": "2024-01-15T09:15:00Z",
      "title": "New device detected",
      "description": "192.168.1.220 first seen on network",
      "resource_id": "660e8400-e29b-41d4-a716-446655440010"
    },
    {
      "type": "alert_resolved",
      "timestamp": "2024-01-15T08:45:00Z",
      "title": "Alert resolved",
      "description": "Traffic spike on backup-server marked as false positive",
      "resource_id": "770e8400-e29b-41d4-a716-446655440000",
      "user": "admin@netsentinel.local"
    }
  ]
}
```

---

## Site Management Endpoints

### GET /sites
List sites (for MSP/multi-tenant).

**Response (200):**
```json
{
  "items": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "Main Office",
      "status": "active",
      "internal_subnets": ["10.0.0.0/24", "192.168.1.0/24"],
      "device_count": 145,
      "open_alerts": 12,
      "last_flow_received": "2024-01-15T10:59:55Z"
    }
  ],
  "total": 1
}
```

### POST /sites
Create a new site.

**Request:**
```json
{
  "name": "Branch Office",
  "description": "Remote branch in Chicago",
  "internal_subnets": ["10.1.0.0/24"]
}
```

**Response (201):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440001",
  "name": "Branch Office",
  "description": "Remote branch in Chicago",
  "status": "onboarding",
  "internal_subnets": ["10.1.0.0/24"],
  "collector_ip": null,
  "collector_port": 2055,
  "onboarding_instructions": {
    "collector_endpoint": "collector.netsentinel.local:2055",
    "example_cisco": "ip flow-export destination collector.netsentinel.local 2055",
    "example_pfsense": "System > NetFlow > Destination: collector.netsentinel.local:2055"
  },
  "created_at": "2024-01-15T11:00:00Z"
}
```

---

## Health Endpoints

### GET /health
Health check for load balancers.

**Response (200):**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "timestamp": "2024-01-15T11:00:00Z"
}
```

### GET /health/detailed
Detailed health check (authenticated).

**Response (200):**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "timestamp": "2024-01-15T11:00:00Z",
  "components": {
    "database": {
      "status": "healthy",
      "latency_ms": 2
    },
    "redis": {
      "status": "healthy",
      "latency_ms": 1
    },
    "celery": {
      "status": "healthy",
      "active_workers": 2,
      "queued_tasks": 15
    },
    "collector": {
      "status": "healthy",
      "flows_per_minute": 20500,
      "last_received": "2024-01-15T10:59:58Z"
    },
    "ml_model": {
      "status": "healthy",
      "active_model": "isolation_forest_v1",
      "last_scored": "2024-01-15T10:55:00Z"
    }
  }
}
```

---

## Error Responses

All endpoints return consistent error responses:

**400 Bad Request:**
```json
{
  "detail": "Invalid site_id format",
  "error_code": "VALIDATION_ERROR",
  "field": "site_id"
}
```

**401 Unauthorized:**
```json
{
  "detail": "Invalid or expired token",
  "error_code": "UNAUTHORIZED"
}
```

**403 Forbidden:**
```json
{
  "detail": "Insufficient permissions for this resource",
  "error_code": "FORBIDDEN"
}
```

**404 Not Found:**
```json
{
  "detail": "Alert not found",
  "error_code": "NOT_FOUND",
  "resource_type": "alert",
  "resource_id": "770e8400-e29b-41d4-a716-446655440999"
}
```

**429 Rate Limited:**
```json
{
  "detail": "Rate limit exceeded",
  "error_code": "RATE_LIMITED",
  "retry_after": 60
}
```

**500 Internal Server Error:**
```json
{
  "detail": "An unexpected error occurred",
  "error_code": "INTERNAL_ERROR",
  "request_id": "req_abc123"
}
```
