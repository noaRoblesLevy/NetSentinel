import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts'
import { format, parseISO } from 'date-fns'
import type { TimeSeriesData } from '@/types'

interface AnomalyChartProps {
  data: TimeSeriesData[]
  threshold?: number
}

export function AnomalyChart({ data, threshold = 0.85 }: AnomalyChartProps) {
  const chartData = data.map((item) => ({
    ...item,
    time: format(parseISO(item.timestamp), 'HH:mm'),
    score: item.value,
  }))

  return (
    <ResponsiveContainer width="100%" height={300}>
      <AreaChart data={chartData}>
        <defs>
          <linearGradient id="anomalyGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3} />
            <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
        <XAxis
          dataKey="time"
          className="text-xs"
          tick={{ fill: 'hsl(var(--muted-foreground))' }}
        />
        <YAxis
          domain={[0, 1]}
          className="text-xs"
          tick={{ fill: 'hsl(var(--muted-foreground))' }}
          tickFormatter={(v) => v.toFixed(1)}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: 'hsl(var(--card))',
            border: '1px solid hsl(var(--border))',
            borderRadius: '8px',
          }}
          formatter={(value: number) => [value.toFixed(3), 'Score']}
        />
        <ReferenceLine
          y={threshold}
          stroke="#f97316"
          strokeDasharray="5 5"
          label={{
            value: 'Alert Threshold',
            position: 'right',
            fill: '#f97316',
            fontSize: 12,
          }}
        />
        <Area
          type="monotone"
          dataKey="score"
          stroke="#ef4444"
          fill="url(#anomalyGradient)"
          strokeWidth={2}
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}
