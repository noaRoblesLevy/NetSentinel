-- NetSentinel Database Schema
-- PostgreSQL with TimescaleDB extension
-- MVP Version 1.0

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- CORE TABLES
-- ============================================================================

-- Sites (Networks/Tenants)
CREATE TABLE sites (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    description TEXT,

    -- Network configuration
    internal_subnets INET[] NOT NULL DEFAULT '{}',  -- e.g., {10.0.0.0/24, 192.168.1.0/24}
    collector_ip INET,
    collector_port INTEGER DEFAULT 2055,

    -- Status
    status VARCHAR(20) DEFAULT 'onboarding' CHECK (status IN ('onboarding', 'learning', 'active', 'paused')),
    learning_started_at TIMESTAMPTZ,
    learning_completed_at TIMESTAMPTZ,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Soft delete
    deleted_at TIMESTAMPTZ
);

CREATE INDEX idx_sites_status ON sites(status) WHERE deleted_at IS NULL;

-- Users
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    full_name VARCHAR(255),

    -- Role and permissions
    role VARCHAR(20) DEFAULT 'viewer' CHECK (role IN ('admin', 'analyst', 'viewer')),

    -- Status
    is_active BOOLEAN DEFAULT TRUE,
    email_verified BOOLEAN DEFAULT FALSE,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    last_login_at TIMESTAMPTZ
);

CREATE INDEX idx_users_email ON users(email);

-- User-Site relationship (for multi-tenant)
CREATE TABLE user_sites (
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    site_id UUID REFERENCES sites(id) ON DELETE CASCADE,
    role VARCHAR(20) DEFAULT 'viewer',
    PRIMARY KEY (user_id, site_id)
);

-- ============================================================================
-- FLOW DATA (High Volume - TimescaleDB Hypertable)
-- ============================================================================

-- Raw Flow Records
CREATE TABLE flows_raw (
    -- Time (required for hypertable)
    ts_start TIMESTAMPTZ NOT NULL,
    ts_end TIMESTAMPTZ NOT NULL,

    -- Identifiers
    site_id UUID NOT NULL REFERENCES sites(id),
    exporter_id VARCHAR(50),  -- IP or identifier of the flow exporter

    -- Flow fields
    src_ip INET NOT NULL,
    dst_ip INET NOT NULL,
    src_port INTEGER,
    dst_port INTEGER,
    protocol SMALLINT NOT NULL,  -- 6=TCP, 17=UDP, 1=ICMP

    -- Metrics
    bytes BIGINT NOT NULL DEFAULT 0,
    packets BIGINT NOT NULL DEFAULT 0,
    duration_ms INTEGER,

    -- TCP flags (if available)
    tcp_flags SMALLINT,

    -- Computed fields (enriched on insert)
    is_internal_src BOOLEAN,
    is_internal_dst BOOLEAN,

    -- Deduplication
    flow_hash BIGINT  -- Hash for dedup if needed
);

-- Convert to hypertable (chunk by 1 hour for MVP scale)
SELECT create_hypertable('flows_raw', 'ts_start', chunk_time_interval => INTERVAL '1 hour');

-- Indexes for common queries
CREATE INDEX idx_flows_raw_site_time ON flows_raw (site_id, ts_start DESC);
CREATE INDEX idx_flows_raw_src_ip ON flows_raw (site_id, src_ip, ts_start DESC);
CREATE INDEX idx_flows_raw_dst_ip ON flows_raw (site_id, dst_ip, ts_start DESC);

-- Retention policy: 30 days for raw flows
SELECT add_retention_policy('flows_raw', INTERVAL '30 days');

-- ============================================================================
-- ASSET DISCOVERY
-- ============================================================================

-- Discovered Assets (Devices)
CREATE TABLE assets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    site_id UUID NOT NULL REFERENCES sites(id),

    -- Identity
    ip INET NOT NULL,
    hostname VARCHAR(255),
    mac_address MACADDR,

    -- Classification
    role_tag VARCHAR(50) DEFAULT 'unknown' CHECK (role_tag IN ('server', 'workstation', 'iot', 'infrastructure', 'unknown', 'custom')),
    custom_name VARCHAR(255),
    subnet_label VARCHAR(100),

    -- Discovery info
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Behavioral summary (updated by aggregation)
    typical_active_hours INT[],  -- e.g., {9,10,11,12,13,14,15,16,17} for 9-5
    avg_daily_flows BIGINT,
    avg_daily_bytes BIGINT,

    -- Status
    is_monitored BOOLEAN DEFAULT TRUE,
    notes TEXT,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(site_id, ip)
);

CREATE INDEX idx_assets_site ON assets(site_id);
CREATE INDEX idx_assets_last_seen ON assets(site_id, last_seen DESC);
CREATE INDEX idx_assets_role ON assets(site_id, role_tag);

-- ============================================================================
-- FEATURE VECTORS (TimescaleDB Hypertable)
-- ============================================================================

-- 5-Minute Aggregated Features per Device
CREATE TABLE features_5m (
    -- Time window
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,

    -- Identifiers
    site_id UUID NOT NULL REFERENCES sites(id),
    asset_id UUID NOT NULL REFERENCES assets(id),

    -- Traffic volume features
    flows_in BIGINT DEFAULT 0,
    flows_out BIGINT DEFAULT 0,
    bytes_in BIGINT DEFAULT 0,
    bytes_out BIGINT DEFAULT 0,
    packets_in BIGINT DEFAULT 0,
    packets_out BIGINT DEFAULT 0,

    -- Connection diversity features
    unique_src_ips INTEGER DEFAULT 0,      -- Devices connecting TO this asset
    unique_dst_ips INTEGER DEFAULT 0,      -- Destinations this asset connects TO
    unique_src_ports INTEGER DEFAULT 0,
    unique_dst_ports INTEGER DEFAULT 0,

    -- Internal vs External
    internal_dst_count INTEGER DEFAULT 0,
    external_dst_count INTEGER DEFAULT 0,
    internal_src_count INTEGER DEFAULT 0,
    external_src_count INTEGER DEFAULT 0,

    -- Entropy features (higher = more diverse)
    dst_port_entropy FLOAT DEFAULT 0,      -- Shannon entropy of destination ports
    dst_ip_entropy FLOAT DEFAULT 0,        -- Shannon entropy of destination IPs
    src_port_entropy FLOAT DEFAULT 0,

    -- Protocol breakdown
    tcp_flows INTEGER DEFAULT 0,
    udp_flows INTEGER DEFAULT 0,
    icmp_flows INTEGER DEFAULT 0,
    other_protocol_flows INTEGER DEFAULT 0,

    -- Connection characteristics
    avg_flow_duration_ms FLOAT,
    avg_bytes_per_flow FLOAT,
    avg_packets_per_flow FLOAT,

    -- Time-based features
    hour_of_day SMALLINT,                  -- 0-23
    day_of_week SMALLINT,                  -- 0-6 (Mon-Sun)
    is_business_hours BOOLEAN,

    -- New/unusual activity flags
    new_dst_ips_count INTEGER DEFAULT 0,   -- Destinations never seen before
    new_dst_ports_count INTEGER DEFAULT 0,

    -- Feature vector version (for schema evolution)
    feature_version SMALLINT DEFAULT 1
);

-- Convert to hypertable
SELECT create_hypertable('features_5m', 'window_start', chunk_time_interval => INTERVAL '1 day');

-- Composite primary key equivalent
CREATE UNIQUE INDEX idx_features_5m_pk ON features_5m (site_id, asset_id, window_start);

-- Query optimization indexes
CREATE INDEX idx_features_5m_asset ON features_5m (asset_id, window_start DESC);

-- Retention: 90 days for features
SELECT add_retention_policy('features_5m', INTERVAL '90 days');

-- ============================================================================
-- ANOMALY SCORES (TimescaleDB Hypertable)
-- ============================================================================

-- Anomaly Scores per Device per Window
CREATE TABLE anomaly_scores_5m (
    -- Time window (matches features_5m)
    window_start TIMESTAMPTZ NOT NULL,

    -- Identifiers
    site_id UUID NOT NULL REFERENCES sites(id),
    asset_id UUID NOT NULL REFERENCES assets(id),

    -- Model info
    model_id VARCHAR(100) NOT NULL,        -- e.g., "isolation_forest_v1_site123"
    model_version INTEGER DEFAULT 1,

    -- Scores
    anomaly_score FLOAT NOT NULL,          -- 0.0 (normal) to 1.0 (anomalous)
    raw_score FLOAT,                       -- Raw model output before normalization

    -- Threshold comparison
    threshold_used FLOAT,
    is_anomaly BOOLEAN DEFAULT FALSE,

    -- Feature contributions (JSONB for flexibility)
    -- e.g., {"unique_dst_ips": 0.35, "bytes_out": 0.28, "dst_port_entropy": 0.15}
    feature_contributions JSONB,

    -- Top contributing features as array for easy display
    -- e.g., ["unique_dst_ips", "bytes_out", "dst_port_entropy"]
    top_features VARCHAR(50)[],

    -- Baseline comparison
    baseline_comparison JSONB,             -- Current vs baseline stats

    -- Computed at
    scored_at TIMESTAMPTZ DEFAULT NOW()
);

-- Convert to hypertable
SELECT create_hypertable('anomaly_scores_5m', 'window_start', chunk_time_interval => INTERVAL '1 day');

-- Indexes
CREATE UNIQUE INDEX idx_scores_5m_pk ON anomaly_scores_5m (site_id, asset_id, window_start);
CREATE INDEX idx_scores_5m_anomaly ON anomaly_scores_5m (site_id, is_anomaly, window_start DESC) WHERE is_anomaly = TRUE;
CREATE INDEX idx_scores_5m_high ON anomaly_scores_5m (site_id, anomaly_score DESC, window_start DESC) WHERE anomaly_score > 0.7;

-- Retention: 90 days
SELECT add_retention_policy('anomaly_scores_5m', INTERVAL '90 days');

-- ============================================================================
-- ALERTS
-- ============================================================================

-- Alert Status Enum
CREATE TYPE alert_status AS ENUM ('open', 'acknowledged', 'investigating', 'resolved', 'false_positive');
CREATE TYPE alert_severity AS ENUM ('low', 'medium', 'high', 'critical');

-- Alerts Table
CREATE TABLE alerts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Identifiers
    site_id UUID NOT NULL REFERENCES sites(id),
    asset_id UUID NOT NULL REFERENCES assets(id),

    -- Alert classification
    alert_type VARCHAR(100) NOT NULL,      -- e.g., "anomaly_detection", "new_device", "threshold_breach"
    severity alert_severity NOT NULL DEFAULT 'medium',

    -- Time range
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ,                  -- NULL if ongoing

    -- Scores
    peak_score FLOAT,
    avg_score FLOAT,

    -- Explanation (structured)
    title VARCHAR(500) NOT NULL,           -- Human-readable title
    description TEXT,                      -- Detailed description

    -- What changed (for explainability)
    -- e.g., {"unique_dst_ips": {"current": 150, "baseline": 12, "change_pct": 1150}}
    explanation JSONB NOT NULL,

    -- Suggested actions
    suggested_actions TEXT[],              -- e.g., ["Check for port scanning", "Review destination IPs"]

    -- Status tracking
    status alert_status DEFAULT 'open',
    status_changed_at TIMESTAMPTZ,
    status_changed_by UUID REFERENCES users(id),

    -- Resolution
    resolution_notes TEXT,

    -- Deduplication
    dedup_key VARCHAR(255),                -- Hash of (site_id, asset_id, alert_type, key_features)

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Notification tracking
    notified_at TIMESTAMPTZ,
    notification_channels VARCHAR(50)[]    -- e.g., {"email", "slack"}
);

-- Indexes
CREATE INDEX idx_alerts_site_status ON alerts(site_id, status, created_at DESC);
CREATE INDEX idx_alerts_site_severity ON alerts(site_id, severity, created_at DESC);
CREATE INDEX idx_alerts_asset ON alerts(asset_id, created_at DESC);
CREATE INDEX idx_alerts_dedup ON alerts(dedup_key) WHERE status = 'open';
CREATE INDEX idx_alerts_created ON alerts(created_at DESC);

-- ============================================================================
-- RULES (Suppression & Allowlists)
-- ============================================================================

CREATE TYPE rule_type AS ENUM ('allowlist', 'suppress', 'threshold', 'custom');
CREATE TYPE rule_action AS ENUM ('ignore', 'reduce_severity', 'tag', 'custom');

CREATE TABLE rules (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    site_id UUID NOT NULL REFERENCES sites(id),

    -- Rule definition
    name VARCHAR(255) NOT NULL,
    description TEXT,
    rule_type rule_type NOT NULL,

    -- Conditions (JSONB for flexibility)
    -- e.g., {"asset_ip": "10.0.0.50", "dst_port": 443}
    -- e.g., {"asset_role": "server", "alert_type": "high_external_connections"}
    conditions JSONB NOT NULL,

    -- What to do when matched
    action rule_action NOT NULL DEFAULT 'ignore',
    action_params JSONB,                   -- e.g., {"reduce_to": "low"} for reduce_severity

    -- Scope
    applies_to_assets UUID[],              -- Empty = all assets
    applies_to_alert_types VARCHAR(100)[], -- Empty = all types

    -- Status
    is_enabled BOOLEAN DEFAULT TRUE,

    -- Stats
    times_matched BIGINT DEFAULT 0,
    last_matched_at TIMESTAMPTZ,

    -- Audit
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Expiration (optional)
    expires_at TIMESTAMPTZ
);

CREATE INDEX idx_rules_site_enabled ON rules(site_id, is_enabled) WHERE is_enabled = TRUE;
CREATE INDEX idx_rules_type ON rules(site_id, rule_type);

-- ============================================================================
-- BASELINE MODELS (Track trained models)
-- ============================================================================

CREATE TABLE baseline_models (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    site_id UUID NOT NULL REFERENCES sites(id),

    -- Model info
    model_type VARCHAR(50) NOT NULL,       -- e.g., "isolation_forest"
    model_version INTEGER NOT NULL,
    model_path VARCHAR(500),               -- Path to serialized model

    -- Training info
    training_started_at TIMESTAMPTZ,
    training_completed_at TIMESTAMPTZ,
    training_window_start TIMESTAMPTZ,
    training_window_end TIMESTAMPTZ,
    samples_count BIGINT,

    -- Model parameters
    parameters JSONB,                      -- e.g., {"n_estimators": 100, "contamination": 0.1}

    -- Performance metrics
    metrics JSONB,                         -- e.g., {"auc": 0.85, "precision": 0.72}

    -- Status
    is_active BOOLEAN DEFAULT FALSE,       -- Only one active per site

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_models_site_active ON baseline_models(site_id, is_active) WHERE is_active = TRUE;

-- ============================================================================
-- NOTIFICATION SETTINGS
-- ============================================================================

CREATE TABLE notification_settings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    site_id UUID NOT NULL REFERENCES sites(id),

    -- Channel type
    channel_type VARCHAR(50) NOT NULL,     -- 'email', 'slack', 'webhook', 'teams'
    channel_name VARCHAR(255),             -- Display name

    -- Configuration (encrypted sensitive data separately)
    config JSONB NOT NULL,                 -- e.g., {"webhook_url": "...", "channel": "#alerts"}

    -- Filters
    min_severity alert_severity DEFAULT 'low',
    alert_types VARCHAR(100)[],            -- Empty = all types

    -- Batching
    batch_interval_minutes INTEGER DEFAULT 0,  -- 0 = immediate

    -- Quiet hours
    quiet_hours_start TIME,                -- e.g., 22:00
    quiet_hours_end TIME,                  -- e.g., 07:00
    quiet_hours_timezone VARCHAR(50) DEFAULT 'UTC',

    -- Status
    is_enabled BOOLEAN DEFAULT TRUE,
    last_sent_at TIMESTAMPTZ,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_notifications_site ON notification_settings(site_id, is_enabled);

-- ============================================================================
-- AUDIT LOG
-- ============================================================================

CREATE TABLE audit_log (
    id UUID DEFAULT uuid_generate_v4(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Who
    user_id UUID REFERENCES users(id),
    user_email VARCHAR(255),

    -- What
    action VARCHAR(100) NOT NULL,          -- e.g., "alert.acknowledge", "rule.create"
    resource_type VARCHAR(50),             -- e.g., "alert", "rule", "asset"
    resource_id UUID,

    -- Details
    details JSONB,                         -- Action-specific details

    -- Context
    ip_address INET,
    user_agent TEXT,

    -- Composite primary key including partition column (required by TimescaleDB)
    PRIMARY KEY (id, created_at)
);

-- Convert to hypertable for automatic partitioning
SELECT create_hypertable('audit_log', 'created_at', chunk_time_interval => INTERVAL '1 month', migrate_data => true);

-- Retention: 1 year
SELECT add_retention_policy('audit_log', INTERVAL '365 days');

CREATE INDEX idx_audit_user ON audit_log(user_id, created_at DESC);
CREATE INDEX idx_audit_resource ON audit_log(resource_type, resource_id, created_at DESC);

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Function to check if an IP is internal to a site
CREATE OR REPLACE FUNCTION is_internal_ip(check_ip INET, site_uuid UUID)
RETURNS BOOLEAN AS $$
DECLARE
    subnets INET[];
    subnet INET;
BEGIN
    SELECT internal_subnets INTO subnets FROM sites WHERE id = site_uuid;
    FOREACH subnet IN ARRAY subnets LOOP
        IF check_ip << subnet THEN
            RETURN TRUE;
        END IF;
    END LOOP;
    RETURN FALSE;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Function to calculate Shannon entropy
CREATE OR REPLACE FUNCTION shannon_entropy(counts BIGINT[])
RETURNS FLOAT AS $$
DECLARE
    total BIGINT := 0;
    entropy FLOAT := 0;
    p FLOAT;
    c BIGINT;
BEGIN
    FOREACH c IN ARRAY counts LOOP
        total := total + c;
    END LOOP;

    IF total = 0 THEN
        RETURN 0;
    END IF;

    FOREACH c IN ARRAY counts LOOP
        IF c > 0 THEN
            p := c::FLOAT / total::FLOAT;
            entropy := entropy - (p * ln(p) / ln(2));
        END IF;
    END LOOP;

    RETURN entropy;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- ============================================================================
-- CONTINUOUS AGGREGATES (Optional optimization for dashboards)
-- ============================================================================

-- Hourly traffic summary per site (for dashboard charts)
CREATE MATERIALIZED VIEW IF NOT EXISTS traffic_hourly
WITH (timescaledb.continuous) AS
SELECT
    site_id,
    time_bucket('1 hour', ts_start) AS hour,
    COUNT(*) AS flow_count,
    SUM(bytes) AS total_bytes,
    SUM(packets) AS total_packets,
    COUNT(DISTINCT src_ip) AS unique_src_ips,
    COUNT(DISTINCT dst_ip) AS unique_dst_ips
FROM flows_raw
GROUP BY site_id, time_bucket('1 hour', ts_start)
WITH NO DATA;

-- Refresh policy
SELECT add_continuous_aggregate_policy('traffic_hourly',
    start_offset => INTERVAL '3 hours',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour');

-- ============================================================================
-- DEFAULT DATA
-- ============================================================================

-- Insert default admin user (password: 'changeme' - MUST be changed)
-- Password hash for 'changeme' using bcrypt
INSERT INTO users (email, hashed_password, full_name, role)
VALUES ('admin@netsentinel.local', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.VTtYNLlYRFKHHi', 'System Admin', 'admin')
ON CONFLICT (email) DO NOTHING;
