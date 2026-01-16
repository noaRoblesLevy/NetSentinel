import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Server, Activity, TrendingUp } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { FlowChart } from '@/components/charts/FlowChart'
import { AnomalyChart } from '@/components/charts/AnomalyChart'
import { SeverityChart } from '@/components/charts/SeverityChart'
import { useSite } from '@/hooks/useSite'
import api from '@/lib/api'
import { formatBytes, formatNumber, formatRelativeTime } from '@/lib/utils'
import { Link } from 'react-router-dom'
import type { Alert } from '@/types'

function StatCard({
  title,
  value,
  icon: Icon,
  description,
  trend,
}: {
  title: string
  value: string | number
  icon: React.ElementType
  description?: string
  trend?: 'up' | 'down' | 'neutral'
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold">{value}</div>
        {description && (
          <p className="text-xs text-muted-foreground">{description}</p>
        )}
      </CardContent>
    </Card>
  )
}

function RecentAlertItem({ alert }: { alert: Alert }) {
  return (
    <Link
      to={`/alerts/${alert.id}`}
      className="flex items-start gap-3 p-3 rounded-lg hover:bg-accent transition-colors"
    >
      <Badge variant={alert.severity as 'critical' | 'high' | 'medium' | 'low'}>
        {alert.severity}
      </Badge>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium truncate">{alert.title}</p>
        <p className="text-xs text-muted-foreground">
          {formatRelativeTime(alert.created_at)}
        </p>
      </div>
    </Link>
  )
}

export function Overview() {
  const { selectedSiteId } = useSite()

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['dashboard-stats', selectedSiteId],
    queryFn: () => api.getDashboardStats(selectedSiteId!),
    enabled: !!selectedSiteId,
  })

  const { data: flowData } = useQuery({
    queryKey: ['flow-timeseries', selectedSiteId],
    queryFn: () => api.getFlowTimeSeries(selectedSiteId!, 24),
    enabled: !!selectedSiteId,
  })

  const { data: anomalyData } = useQuery({
    queryKey: ['anomaly-timeseries', selectedSiteId],
    queryFn: () => api.getAnomalyTimeSeries(selectedSiteId!, 24),
    enabled: !!selectedSiteId,
  })

  const { data: severityData } = useQuery({
    queryKey: ['alerts-severity', selectedSiteId],
    queryFn: () => api.getAlertsBySeverity(selectedSiteId!),
    enabled: !!selectedSiteId,
  })

  const { data: recentAlerts } = useQuery({
    queryKey: ['recent-alerts', selectedSiteId],
    queryFn: () => api.getAlerts(selectedSiteId!, { status: ['open'] }, 1, 5),
    enabled: !!selectedSiteId,
  })

  if (!selectedSiteId) {
    return (
      <div className="flex h-[50vh] items-center justify-center">
        <div className="text-center">
          <Server className="mx-auto h-12 w-12 text-muted-foreground" />
          <h2 className="mt-4 text-lg font-semibold">No Site Selected</h2>
          <p className="text-muted-foreground">
            Please select a site from the sidebar to view the dashboard.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Overview</h1>
        <p className="text-muted-foreground">
          Network security monitoring dashboard
        </p>
      </div>

      {/* Stats Grid */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <StatCard
          title="Active Alerts"
          value={stats?.active_alerts || 0}
          icon={AlertTriangle}
          description={`${stats?.critical_alerts || 0} critical, ${stats?.high_alerts || 0} high`}
        />
        <StatCard
          title="Monitored Assets"
          value={stats?.total_assets || 0}
          icon={Server}
        />
        <StatCard
          title="Flows (24h)"
          value={formatNumber(stats?.flows_24h || 0)}
          icon={Activity}
        />
        <StatCard
          title="Traffic (24h)"
          value={formatBytes(stats?.bytes_24h || 0)}
          icon={TrendingUp}
        />
      </div>

      {/* Charts */}
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Network Traffic</CardTitle>
          </CardHeader>
          <CardContent>
            <Tabs defaultValue="flows">
              <TabsList>
                <TabsTrigger value="flows">Flows</TabsTrigger>
                <TabsTrigger value="bytes">Bytes</TabsTrigger>
              </TabsList>
              <TabsContent value="flows">
                {flowData && <FlowChart data={flowData} metric="flows" />}
              </TabsContent>
              <TabsContent value="bytes">
                {flowData && <FlowChart data={flowData} metric="bytes" />}
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Alerts by Severity</CardTitle>
          </CardHeader>
          <CardContent>
            {severityData && <SeverityChart data={severityData} />}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Anomaly Scores</CardTitle>
          </CardHeader>
          <CardContent>
            {anomalyData && <AnomalyChart data={anomalyData} />}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>Recent Alerts</CardTitle>
            <Link
              to="/alerts"
              className="text-sm text-primary hover:underline"
            >
              View all
            </Link>
          </CardHeader>
          <CardContent>
            <div className="space-y-1">
              {recentAlerts?.items?.length ? (
                recentAlerts.items.map((alert) => (
                  <RecentAlertItem key={alert.id} alert={alert} />
                ))
              ) : (
                <p className="text-center text-muted-foreground py-4">
                  No open alerts
                </p>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
