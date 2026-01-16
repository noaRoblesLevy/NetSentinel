import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowLeft,
  Server,
  Activity,
  AlertTriangle,
  Clock,
  Network,
  Wifi,
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { FlowChart } from '@/components/charts/FlowChart'
import { AnomalyChart } from '@/components/charts/AnomalyChart'
import api from '@/lib/api'
import { formatRelativeTime, formatBytes, formatNumber } from '@/lib/utils'

export function DeviceProfile() {
  const { id } = useParams<{ id: string }>()

  const { data: device, isLoading } = useQuery({
    queryKey: ['device', id],
    queryFn: () => api.getAsset(id!),
    enabled: !!id,
  })

  const { data: deviceStats } = useQuery({
    queryKey: ['device-stats', id],
    queryFn: () => api.getAssetStats(id!),
    enabled: !!id,
  })

  const { data: flowData } = useQuery({
    queryKey: ['device-flows', id],
    queryFn: () => api.getAssetFlows(id!, 24),
    enabled: !!id,
  })

  const { data: anomalyData } = useQuery({
    queryKey: ['device-anomalies', id],
    queryFn: () => api.getAssetAnomalies(id!, 24),
    enabled: !!id,
  })

  const { data: alertsData } = useQuery({
    queryKey: ['device-alerts', id],
    queryFn: () => api.getAssetAlerts(id!, 1, 10),
    enabled: !!id,
  })

  const { data: featuresData } = useQuery({
    queryKey: ['device-features', id],
    queryFn: () => api.getAssetFeatures(id!, 10),
    enabled: !!id,
  })

  if (isLoading) {
    return (
      <div className="flex h-[50vh] items-center justify-center">
        <div className="text-muted-foreground">Loading device...</div>
      </div>
    )
  }

  if (!device) {
    return (
      <div className="flex h-[50vh] items-center justify-center">
        <div className="text-center">
          <Server className="mx-auto h-12 w-12 text-muted-foreground" />
          <h2 className="mt-4 text-lg font-semibold">Device Not Found</h2>
          <p className="text-muted-foreground">
            The device you're looking for doesn't exist.
          </p>
          <Button className="mt-4" asChild>
            <Link to="/devices">Back to Devices</Link>
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="space-y-1">
        <Link
          to="/devices"
          className="inline-flex items-center text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="mr-1 h-4 w-4" />
          Back to Devices
        </Link>
        <div className="flex items-center gap-4">
          <Server className="h-8 w-8 text-muted-foreground" />
          <div>
            <h1 className="text-2xl font-bold font-mono">{device.ip_address}</h1>
            <p className="text-muted-foreground">
              {device.hostname || 'Unknown hostname'}
            </p>
          </div>
        </div>
      </div>

      {/* Device Info Cards */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <Wifi className="h-4 w-4" />
              MAC Address
            </CardTitle>
          </CardHeader>
          <CardContent>
            <span className="font-mono">
              {device.mac_address || 'Unknown'}
            </span>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <Network className="h-4 w-4" />
              Subnet
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Badge variant="outline">{device.subnet}</Badge>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <Clock className="h-4 w-4" />
              Last Seen
            </CardTitle>
          </CardHeader>
          <CardContent>
            {formatRelativeTime(device.last_seen)}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <AlertTriangle className="h-4 w-4" />
              Active Alerts
            </CardTitle>
          </CardHeader>
          <CardContent>
            {device.active_alerts > 0 ? (
              <Badge variant="critical">{device.active_alerts}</Badge>
            ) : (
              <span className="text-green-600">None</span>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Traffic Stats */}
      {deviceStats && (
        <div className="grid gap-4 md:grid-cols-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Flows (24h)
              </CardTitle>
            </CardHeader>
            <CardContent>
              <span className="text-2xl font-bold">
                {formatNumber(deviceStats.flows_24h)}
              </span>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Bytes In (24h)
              </CardTitle>
            </CardHeader>
            <CardContent>
              <span className="text-2xl font-bold">
                {formatBytes(deviceStats.bytes_in_24h)}
              </span>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Bytes Out (24h)
              </CardTitle>
            </CardHeader>
            <CardContent>
              <span className="text-2xl font-bold">
                {formatBytes(deviceStats.bytes_out_24h)}
              </span>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Avg Anomaly Score
              </CardTitle>
            </CardHeader>
            <CardContent>
              <span className="text-2xl font-bold font-mono">
                {deviceStats.avg_anomaly_score?.toFixed(3) || '0.000'}
              </span>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Charts */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Activity className="h-5 w-5" />
              Network Traffic (24h)
            </CardTitle>
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
            <CardTitle>Anomaly Scores (24h)</CardTitle>
          </CardHeader>
          <CardContent>
            {anomalyData && <AnomalyChart data={anomalyData} />}
          </CardContent>
        </Card>
      </div>

      {/* Recent Alerts */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Recent Alerts</CardTitle>
          <Link
            to={`/alerts?asset_id=${id}`}
            className="text-sm text-primary hover:underline"
          >
            View all
          </Link>
        </CardHeader>
        <CardContent>
          {alertsData?.items?.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Severity</TableHead>
                  <TableHead>Title</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Time</TableHead>
                  <TableHead></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {alertsData.items.map((alert) => (
                  <TableRow key={alert.id}>
                    <TableCell>
                      <Badge variant={alert.severity as 'critical' | 'high' | 'medium' | 'low'}>
                        {alert.severity}
                      </Badge>
                    </TableCell>
                    <TableCell>{alert.title}</TableCell>
                    <TableCell>
                      <span className="text-sm capitalize">
                        {alert.status.replace('_', ' ')}
                      </span>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatRelativeTime(alert.created_at)}
                    </TableCell>
                    <TableCell>
                      <Link to={`/alerts/${alert.id}`}>
                        <Button variant="ghost" size="sm">
                          View
                        </Button>
                      </Link>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <p className="text-center text-muted-foreground py-4">
              No alerts for this device
            </p>
          )}
        </CardContent>
      </Card>

      {/* Recent Features */}
      <Card>
        <CardHeader>
          <CardTitle>Recent Feature Vectors (5-min windows)</CardTitle>
        </CardHeader>
        <CardContent>
          {featuresData?.length ? (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Time</TableHead>
                    <TableHead>Flows</TableHead>
                    <TableHead>Bytes</TableHead>
                    <TableHead>Unique Dst IPs</TableHead>
                    <TableHead>Unique Dst Ports</TableHead>
                    <TableHead>Port Entropy</TableHead>
                    <TableHead>IP Entropy</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {featuresData.map((feature, index) => (
                    <TableRow key={index}>
                      <TableCell className="text-muted-foreground">
                        {formatRelativeTime(feature.window_start)}
                      </TableCell>
                      <TableCell>{formatNumber(feature.flow_count)}</TableCell>
                      <TableCell>{formatBytes(feature.total_bytes)}</TableCell>
                      <TableCell>{feature.unique_dst_ips}</TableCell>
                      <TableCell>{feature.unique_dst_ports}</TableCell>
                      <TableCell className="font-mono">
                        {feature.dst_port_entropy?.toFixed(3) || '0.000'}
                      </TableCell>
                      <TableCell className="font-mono">
                        {feature.dst_ip_entropy?.toFixed(3) || '0.000'}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <p className="text-center text-muted-foreground py-4">
              No feature data available
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
