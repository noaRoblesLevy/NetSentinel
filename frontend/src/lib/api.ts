import axios, { AxiosInstance, AxiosError } from 'axios'
import type {
  Alert,
  AlertFilters,
  Asset,
  AuthResponse,
  DashboardStats,
  FeatureVector,
  FlowStats,
  LoginRequest,
  NotificationSettings,
  PaginatedResponse,
  Rule,
  Site,
  TimeSeriesData,
  User,
} from '@/types'

const API_BASE_URL = import.meta.env.VITE_API_URL || '/api/v1'

class ApiClient {
  private client: AxiosInstance
  private _isAuthenticated: boolean = false

  constructor() {
    this.client = axios.create({
      baseURL: API_BASE_URL,
      headers: {
        'Content-Type': 'application/json',
      },
      // Enable sending cookies with requests (httpOnly cookie auth)
      withCredentials: true,
    })

    // Check if we have a session by calling /auth/me
    // This is done asynchronously on first load
    this.checkAuth()

    // Response interceptor for error handling
    this.client.interceptors.response.use(
      (response) => response,
      (error: AxiosError) => {
        if (error.response?.status === 401) {
          this._isAuthenticated = false
          // Don't redirect if we're already on login page
          if (!window.location.pathname.includes('/login')) {
            window.location.href = '/login'
          }
        }
        return Promise.reject(error)
      }
    )
  }

  private async checkAuth(): Promise<void> {
    try {
      await this.client.get('/auth/me')
      this._isAuthenticated = true
    } catch {
      this._isAuthenticated = false
    }
  }

  setAuthenticated(value: boolean) {
    this._isAuthenticated = value
  }

  isAuthenticated(): boolean {
    return this._isAuthenticated
  }

  // Auth endpoints
  async login(credentials: LoginRequest): Promise<AuthResponse> {
    const params = new URLSearchParams()
    params.append('username', credentials.email)
    params.append('password', credentials.password)

    const response = await this.client.post<AuthResponse>('/auth/login', params, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    })

    // Mark as authenticated (cookies are set automatically by the server)
    this._isAuthenticated = true
    return response.data
  }

  async logout(): Promise<void> {
    try {
      await this.client.post('/auth/logout')
    } finally {
      // Cookies are cleared by the server
      this._isAuthenticated = false
    }
  }

  async refreshTokens(): Promise<void> {
    try {
      // The refresh token is sent via httpOnly cookie automatically
      await this.client.post('/auth/refresh')
      this._isAuthenticated = true
    } catch {
      this._isAuthenticated = false
      throw new Error('Session expired')
    }
  }

  async getCurrentUser(): Promise<User> {
    const response = await this.client.get<User>('/auth/me')
    return response.data
  }

  async updateProfile(data: { full_name?: string; email?: string }): Promise<User> {
    const response = await this.client.patch<User>('/auth/me', data)
    return response.data
  }

  async changePassword(currentPassword: string, newPassword: string): Promise<void> {
    await this.client.post('/auth/change-password', {
      current_password: currentPassword,
      new_password: newPassword,
    })
    // Password change invalidates all sessions, so mark as unauthenticated
    this._isAuthenticated = false
  }

  async forgotPassword(email: string): Promise<{ message: string }> {
    const response = await this.client.post<{ message: string }>('/auth/forgot-password', { email })
    return response.data
  }

  async resetPassword(token: string, newPassword: string): Promise<{ message: string }> {
    const response = await this.client.post<{ message: string }>('/auth/reset-password', {
      token,
      new_password: newPassword,
    })
    return response.data
  }

  // Settings
  async getNotificationSettings(siteId: string): Promise<NotificationSettings> {
    const response = await this.client.get<{ site_id: string; settings: NotificationSettings }>(
      `/settings/notifications/${siteId}`
    )
    return response.data.settings
  }

  async updateNotificationSettings(siteId: string, settings: NotificationSettings): Promise<NotificationSettings> {
    const response = await this.client.put<{ site_id: string; settings: NotificationSettings }>(
      `/settings/notifications/${siteId}`,
      settings
    )
    return response.data.settings
  }

  // Sites
  async getSites(): Promise<Site[]> {
    const response = await this.client.get<Site[]>('/sites')
    return response.data
  }

  async getSite(siteId: string): Promise<Site> {
    const response = await this.client.get<Site>(`/sites/${siteId}`)
    return response.data
  }

  // Dashboard
  async getDashboardStats(siteId: string): Promise<DashboardStats> {
    const response = await this.client.get<DashboardStats>(`/dashboard/stats`, {
      params: { site_id: siteId },
    })
    return response.data
  }

  async getFlowTimeSeries(
    siteId: string,
    hours: number = 24
  ): Promise<FlowStats[]> {
    const response = await this.client.get<FlowStats[]>(`/dashboard/flows/timeseries`, {
      params: { site_id: siteId, hours },
    })
    return response.data
  }

  async getAnomalyTimeSeries(
    siteId: string,
    hours: number = 24
  ): Promise<TimeSeriesData[]> {
    const response = await this.client.get<TimeSeriesData[]>(`/dashboard/anomalies/timeseries`, {
      params: { site_id: siteId, hours },
    })
    return response.data
  }

  // Alerts
  async getAlerts(
    siteId: string,
    filters?: AlertFilters,
    page: number = 1,
    pageSize: number = 20
  ): Promise<PaginatedResponse<Alert>> {
    const response = await this.client.get<PaginatedResponse<Alert>>('/alerts', {
      params: {
        site_id: siteId,
        page,
        page_size: pageSize,
        ...filters,
      },
    })
    return response.data
  }

  async getAlert(alertId: string): Promise<Alert> {
    const response = await this.client.get<Alert>(`/alerts/${alertId}`)
    return response.data
  }

  async updateAlertStatus(
    alertId: string,
    status: string,
    notes?: string
  ): Promise<Alert> {
    const response = await this.client.patch<Alert>(`/alerts/${alertId}`, {
      status,
      resolution_notes: notes,
    })
    return response.data
  }

  async getAlertsBySeverity(siteId: string): Promise<Record<string, number>> {
    const response = await this.client.get<Record<string, number>>(`/alerts/by-severity`, {
      params: { site_id: siteId },
    })
    return response.data
  }

  // Assets
  async getAssets(
    siteId: string,
    filters?: { search?: string; subnet?: string },
    page: number = 1,
    pageSize: number = 50
  ): Promise<PaginatedResponse<Asset>> {
    const response = await this.client.get<PaginatedResponse<Asset>>('/assets', {
      params: { site_id: siteId, page, page_size: pageSize, ...filters },
    })
    return response.data
  }

  async getSubnets(siteId: string): Promise<string[]> {
    const response = await this.client.get<string[]>('/assets/subnets', {
      params: { site_id: siteId },
    })
    return response.data
  }

  async getAsset(assetId: string): Promise<Asset> {
    const response = await this.client.get<Asset>(`/assets/${assetId}`)
    return response.data
  }

  async updateAsset(
    assetId: string,
    data: Partial<Asset>
  ): Promise<Asset> {
    const response = await this.client.patch<Asset>(`/assets/${assetId}`, data)
    return response.data
  }

  async getAssetAlerts(
    assetId: string,
    page: number = 1,
    pageSize: number = 10
  ): Promise<PaginatedResponse<Alert>> {
    const response = await this.client.get<PaginatedResponse<Alert>>(
      `/assets/${assetId}/alerts`,
      { params: { page, page_size: pageSize } }
    )
    return response.data
  }

  async getAssetStats(assetId: string): Promise<{
    flows_24h: number
    bytes_in_24h: number
    bytes_out_24h: number
    avg_anomaly_score: number
  }> {
    const response = await this.client.get(`/assets/${assetId}/stats`)
    return response.data
  }

  async getAssetFlows(assetId: string, hours: number = 24): Promise<FlowStats[]> {
    const response = await this.client.get<FlowStats[]>(
      `/assets/${assetId}/flows/timeseries`,
      { params: { hours } }
    )
    return response.data
  }

  async getAssetAnomalies(
    assetId: string,
    hours: number = 24
  ): Promise<TimeSeriesData[]> {
    const response = await this.client.get<TimeSeriesData[]>(
      `/assets/${assetId}/anomalies/timeseries`,
      { params: { hours } }
    )
    return response.data
  }

  async getAssetFeatures(
    assetId: string,
    hours: number = 24
  ): Promise<FeatureVector[]> {
    const response = await this.client.get<FeatureVector[]>(
      `/features/asset/${assetId}/timeline`,
      { params: { hours } }
    )
    return response.data
  }

  // Features
  async getFeatures(
    siteId: string,
    params?: {
      asset_id?: string
      start_time?: string
      end_time?: string
      min_entropy?: number
      limit?: number
    }
  ): Promise<FeatureVector[]> {
    const response = await this.client.get<FeatureVector[]>('/features', {
      params: { site_id: siteId, ...params },
    })
    return response.data
  }

  async getHighEntropyFeatures(
    siteId: string,
    threshold: number = 3.0,
    hours: number = 24
  ): Promise<FeatureVector[]> {
    const response = await this.client.get<FeatureVector[]>('/features/high-entropy', {
      params: { site_id: siteId, threshold, hours },
    })
    return response.data
  }

  // Rules
  async getRules(siteId: string): Promise<Rule[]> {
    const response = await this.client.get<Rule[]>('/rules', {
      params: { site_id: siteId },
    })
    return response.data
  }

  async getRule(ruleId: string): Promise<Rule> {
    const response = await this.client.get<Rule>(`/rules/${ruleId}`)
    return response.data
  }

  async createRule(siteId: string, rule: Partial<Rule>): Promise<Rule> {
    const response = await this.client.post<Rule>('/rules', {
      ...rule,
      site_id: siteId,
    })
    return response.data
  }

  async updateRule(ruleId: string, data: Partial<Rule>): Promise<Rule> {
    const response = await this.client.patch<Rule>(`/rules/${ruleId}`, data)
    return response.data
  }

  async deleteRule(ruleId: string): Promise<void> {
    await this.client.delete(`/rules/${ruleId}`)
  }

  async toggleRule(ruleId: string, enabled: boolean): Promise<Rule> {
    const response = await this.client.patch<Rule>(`/rules/${ruleId}`, {
      is_enabled: enabled,
    })
    return response.data
  }

  // Health & Status
  async healthCheck(): Promise<{ status: string }> {
    const response = await this.client.get<{ status: string }>('/health')
    return response.data
  }

  async getSiteStatus(siteId: string): Promise<SiteStatus> {
    const response = await this.client.get<SiteStatus>(`/status/site/${siteId}`)
    return response.data
  }
}

// Site Status Types
export interface LearningStatus {
  is_learning: boolean
  phase: 'not_started' | 'collecting' | 'training' | 'complete'
  progress_days: number
  target_days: number
  progress_percent: number
  estimated_completion: string | null
  data_quality: 'insufficient' | 'poor' | 'fair' | 'good'
  current_assets: number
  min_assets_for_training: number
  can_transition: boolean
  alerts_suppressed: boolean
  message: string
}

export interface SiteStatus {
  site_id: string
  site_name: string
  flow_status: 'unknown' | 'receiving' | 'no_data' | 'stale' | 'error'
  last_flow_received: string | null
  flows_last_hour: number
  flows_last_5min: number
  flows_last_24h: number
  bytes_last_24h: number
  learning: LearningStatus
  active_alerts: number
  last_anomaly_score: number | null
  model_trained: boolean
  model_last_trained: string | null
  last_check: string
  error_message: string | null
  warnings: string[]
}

export const api = new ApiClient()
export default api
