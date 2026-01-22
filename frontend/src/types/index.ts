// API Types for NetSentinel

export interface User {
  id: string
  email: string
  full_name: string
  role: 'admin' | 'analyst' | 'viewer'
  is_active: boolean
}

export interface Site {
  id: string
  name: string
  description?: string
  internal_subnets: string[]
  status: 'onboarding' | 'learning' | 'active' | 'paused'
  created_at: string
}

export interface Asset {
  id: string
  site_id: string
  ip: string
  ip_address: string
  hostname?: string
  custom_name?: string
  mac_address?: string
  asset_type?: string
  criticality?: 'low' | 'medium' | 'high' | 'critical'
  subnet: string
  first_seen: string
  last_seen: string
  tags?: string[]
  active_alerts: number
}

export interface Alert {
  id: string
  site_id: string
  asset_id: string
  alert_type: string
  severity: 'low' | 'medium' | 'high' | 'critical'
  status: 'open' | 'acknowledged' | 'investigating' | 'resolved' | 'false_positive'
  title: string
  description?: string
  peak_score: number
  avg_score?: number
  start_time: string
  end_time?: string
  explanation: AlertExplanation
  suggested_actions?: string[]
  created_at: string
  updated_at?: string
}

export interface AlertExplanation {
  summary: string
  severity_reason: string
  top_deviations: FeatureDeviation[]
  statistics: {
    peak_score: number
    avg_score: number
    consecutive_windows: number
    window_start: string
    window_end: string
  }
}

export interface FeatureDeviation {
  feature: string
  current: number
  baseline: number
  deviation_pct: number
  multiplier: number
  direction: 'increase' | 'decrease'
}

export interface Rule {
  id: string
  site_id: string
  name: string
  description?: string
  rule_type: 'allowlist' | 'suppress' | 'threshold' | 'persistence' | 'rate' | 'baseline' | 'custom'
  conditions: Record<string, unknown>
  config: {
    threshold?: number
    window_count?: number
    [key: string]: unknown
  }
  action: 'ignore' | 'reduce_severity' | 'tag' | 'custom'
  severity: 'low' | 'medium' | 'high' | 'critical'
  enabled: boolean
  is_enabled: boolean
  times_matched: number
  last_matched_at?: string
  created_at: string
}

export type AlertRule = Rule

export interface FeatureVector {
  window_start: string
  window_end: string
  site_id: string
  asset_id: string
  asset_ip?: string
  flow_count: number
  total_bytes: number
  flows_in: number
  flows_out: number
  bytes_in: number
  bytes_out: number
  packets_in: number
  packets_out: number
  unique_src_ips: number
  unique_dst_ips: number
  unique_src_ports: number
  unique_dst_ports: number
  dst_port_entropy: number
  dst_ip_entropy: number
  src_port_entropy: number
  tcp_flows: number
  udp_flows: number
  icmp_flows: number
}

export interface AnomalyScore {
  window_start: string
  site_id: string
  asset_id: string
  anomaly_score: number
  is_anomaly: boolean
  model_id: string
}

export interface DashboardStats {
  total_assets: number
  active_alerts: number
  critical_alerts: number
  high_alerts: number
  flows_24h: number
  bytes_24h: number
  anomalies_24h: number
}

export interface TimeSeriesData {
  timestamp: string
  value: number
}

export interface FlowStats {
  timestamp: string
  flows_in: number
  flows_out: number
  bytes_in: number
  bytes_out: number
}

// Filter types
export interface AlertFilters {
  severity?: string[]
  status?: string[]
  asset_id?: string
  start_time?: string
  end_time?: string
}

export interface TimeRange {
  start: Date
  end: Date
  label: string
}

// Auth types
export interface LoginRequest {
  email: string
  password: string
}

export interface AuthResponse {
  access_token: string
  token_type: string
  user: User
}

// Pagination
export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  pages: number
}

// Settings
export interface NotificationSettings {
  email_enabled: boolean
  email_address?: string
  webhook_enabled: boolean
  webhook_url?: string
  slack_enabled: boolean
  slack_webhook_url?: string
  min_severity: 'low' | 'medium' | 'high' | 'critical'
}
