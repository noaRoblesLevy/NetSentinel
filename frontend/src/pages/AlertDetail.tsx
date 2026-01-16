import { useParams, Link, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  AlertTriangle,
  Clock,
  Server,
  TrendingUp,
  TrendingDown,
  CheckCircle,
  XCircle,
  Eye,
  Search
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import api from '@/lib/api'
import { formatRelativeTime, getSeverityColor, getStatusColor } from '@/lib/utils'

const STATUSES = [
  { value: 'open', label: 'Open', icon: AlertTriangle },
  { value: 'acknowledged', label: 'Acknowledged', icon: Eye },
  { value: 'investigating', label: 'Investigating', icon: Search },
  { value: 'resolved', label: 'Resolved', icon: CheckCircle },
  { value: 'false_positive', label: 'False Positive', icon: XCircle },
]

export function AlertDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data: alert, isLoading } = useQuery({
    queryKey: ['alert', id],
    queryFn: () => api.getAlert(id!),
    enabled: !!id,
  })

  const updateStatusMutation = useMutation({
    mutationFn: (status: string) => api.updateAlertStatus(id!, status),
    onMutate: async (newStatus) => {
      // Cancel any outgoing refetches
      await queryClient.cancelQueries({ queryKey: ['alert', id] })

      // Snapshot previous value
      const previousAlert = queryClient.getQueryData(['alert', id])

      // Optimistically update the cache
      queryClient.setQueryData(['alert', id], (old: any) => ({
        ...old,
        status: newStatus,
      }))

      return { previousAlert }
    },
    onError: (_err, _newStatus, context) => {
      // Rollback on error
      if (context?.previousAlert) {
        queryClient.setQueryData(['alert', id], context.previousAlert)
      }
    },
    onSettled: () => {
      // Refetch to ensure sync with server
      queryClient.invalidateQueries({ queryKey: ['alert', id] })
      queryClient.invalidateQueries({ queryKey: ['alerts'] })
    },
  })

  if (isLoading) {
    return (
      <div className="flex h-[50vh] items-center justify-center">
        <div className="text-muted-foreground">Loading alert...</div>
      </div>
    )
  }

  if (!alert) {
    return (
      <div className="flex h-[50vh] items-center justify-center">
        <div className="text-center">
          <AlertTriangle className="mx-auto h-12 w-12 text-muted-foreground" />
          <h2 className="mt-4 text-lg font-semibold">Alert Not Found</h2>
          <p className="text-muted-foreground">
            The alert you're looking for doesn't exist.
          </p>
          <Button className="mt-4" onClick={() => navigate('/alerts')}>
            Back to Alerts
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="space-y-1">
          <Link
            to="/alerts"
            className="inline-flex items-center text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="mr-1 h-4 w-4" />
            Back to Alerts
          </Link>
          <h1 className="text-2xl font-bold">{alert.title}</h1>
          <div className="flex items-center gap-3">
            <Badge variant={alert.severity as 'critical' | 'high' | 'medium' | 'low'}>
              {alert.severity}
            </Badge>
            <span className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${getStatusColor(alert.status)}`}>
              {alert.status.replace('_', ' ')}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Select
            value={alert.status}
            onValueChange={(status) => updateStatusMutation.mutate(status)}
          >
            <SelectTrigger className="w-44">
              <SelectValue placeholder="Update status" />
            </SelectTrigger>
            <SelectContent>
              {STATUSES.map((s) => (
                <SelectItem key={s.value} value={s.value}>
                  <span className="flex items-center gap-2">
                    <s.icon className="h-4 w-4" />
                    {s.label}
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Info Cards */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Peak Score
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold font-mono">
              {alert.peak_score.toFixed(3)}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Asset
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Link
              to={`/devices/${alert.asset_id}`}
              className="text-lg font-medium text-primary hover:underline flex items-center gap-2"
            >
              <Server className="h-4 w-4" />
              View Device
            </Link>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Created
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2">
              <Clock className="h-4 w-4 text-muted-foreground" />
              <span>{formatRelativeTime(alert.created_at)}</span>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Alert Type
            </CardTitle>
          </CardHeader>
          <CardContent>
            <span className="text-lg font-medium capitalize">
              {alert.alert_type.replace('_', ' ')}
            </span>
          </CardContent>
        </Card>
      </div>

      {/* Description */}
      {alert.description && (
        <Card>
          <CardHeader>
            <CardTitle>Description</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-muted-foreground">{alert.description}</p>
          </CardContent>
        </Card>
      )}

      {/* Feature Deviations */}
      {alert.explanation?.top_deviations && alert.explanation.top_deviations.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Feature Deviations</CardTitle>
            <p className="text-sm text-muted-foreground">
              Top anomalous features compared to baseline behavior
            </p>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {alert.explanation.top_deviations.map((deviation, index) => (
                <div
                  key={index}
                  className="flex items-center justify-between p-4 rounded-lg bg-muted/50"
                >
                  <div className="flex items-center gap-3">
                    {deviation.direction === 'increase' ? (
                      <TrendingUp className="h-5 w-5 text-red-500" />
                    ) : (
                      <TrendingDown className="h-5 w-5 text-blue-500" />
                    )}
                    <div>
                      <p className="font-medium">{formatFeatureName(deviation.feature)}</p>
                      <p className="text-sm text-muted-foreground">
                        Baseline: {formatFeatureValue(deviation.feature, deviation.baseline)}
                      </p>
                    </div>
                  </div>
                  <div className="text-right">
                    <p className="font-mono text-lg">
                      {formatFeatureValue(deviation.feature, deviation.current)}
                    </p>
                    <p className={`text-sm font-medium ${
                      deviation.deviation_pct > 100 ? 'text-red-500' : 'text-yellow-500'
                    }`}>
                      {deviation.direction === 'increase' ? '+' : '-'}
                      {Math.abs(deviation.deviation_pct).toFixed(0)}% ({deviation.multiplier.toFixed(1)}x)
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Raw Explanation JSON */}
      <Card>
        <CardHeader>
          <CardTitle>Raw Explanation Data</CardTitle>
        </CardHeader>
        <CardContent>
          <pre className="p-4 rounded-lg bg-muted overflow-auto text-sm">
            {JSON.stringify(alert.explanation, null, 2)}
          </pre>
        </CardContent>
      </Card>
    </div>
  )
}

function formatFeatureName(feature: string): string {
  return feature
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

function formatFeatureValue(feature: string, value: number): string {
  if (feature.includes('bytes')) {
    return formatBytes(value)
  }
  if (feature.includes('entropy')) {
    return value.toFixed(3)
  }
  if (feature.includes('ratio') || feature.includes('pct')) {
    return `${(value * 100).toFixed(1)}%`
  }
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 })
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`
}
