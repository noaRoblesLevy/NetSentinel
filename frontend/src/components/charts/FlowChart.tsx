import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts'
import { format, parseISO } from 'date-fns'
import { formatBytes, formatNumber } from '@/lib/utils'
import type { FlowStats } from '@/types'

interface FlowChartProps {
  data: FlowStats[]
  metric: 'flows' | 'bytes'
}

export function FlowChart({ data, metric }: FlowChartProps) {
  const formatValue = metric === 'bytes' ? formatBytes : formatNumber

  const chartData = data.map((item) => ({
    ...item,
    time: format(parseISO(item.timestamp), 'HH:mm'),
    inbound: metric === 'bytes' ? item.bytes_in : item.flows_in,
    outbound: metric === 'bytes' ? item.bytes_out : item.flows_out,
  }))

  return (
    <ResponsiveContainer width="100%" height={300}>
      <LineChart data={chartData}>
        <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
        <XAxis
          dataKey="time"
          className="text-xs"
          tick={{ fill: 'hsl(var(--muted-foreground))' }}
        />
        <YAxis
          className="text-xs"
          tick={{ fill: 'hsl(var(--muted-foreground))' }}
          tickFormatter={formatValue}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: 'hsl(var(--card))',
            border: '1px solid hsl(var(--border))',
            borderRadius: '8px',
          }}
          formatter={(value: number) => [formatValue(value), '']}
        />
        <Legend />
        <Line
          type="monotone"
          dataKey="inbound"
          name="Inbound"
          stroke="hsl(var(--primary))"
          strokeWidth={2}
          dot={false}
        />
        <Line
          type="monotone"
          dataKey="outbound"
          name="Outbound"
          stroke="#10b981"
          strokeWidth={2}
          dot={false}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}
