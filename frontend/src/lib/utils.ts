import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'
import { format, formatDistanceToNow, parseISO } from 'date-fns'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'

  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))

  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`
}

export function formatNumber(num: number): string {
  if (num >= 1000000) {
    return `${(num / 1000000).toFixed(1)}M`
  }
  if (num >= 1000) {
    return `${(num / 1000).toFixed(1)}K`
  }
  return num.toString()
}

export function formatDateTime(dateString: string): string {
  try {
    return format(parseISO(dateString), 'MMM d, yyyy HH:mm')
  } catch {
    return dateString
  }
}

export function formatDate(dateString: string): string {
  try {
    return format(parseISO(dateString), 'MMM d, yyyy')
  } catch {
    return dateString
  }
}

export function formatTime(dateString: string): string {
  try {
    return format(parseISO(dateString), 'HH:mm:ss')
  } catch {
    return dateString
  }
}

export function formatRelativeTime(dateString: string): string {
  try {
    return formatDistanceToNow(parseISO(dateString), { addSuffix: true })
  } catch {
    return dateString
  }
}

export function getSeverityColor(severity: string): string {
  const colors: Record<string, string> = {
    critical: 'text-red-600 bg-red-100',
    high: 'text-orange-600 bg-orange-100',
    medium: 'text-yellow-600 bg-yellow-100',
    low: 'text-cyan-600 bg-cyan-100',
  }
  return colors[severity] || 'text-gray-600 bg-gray-100'
}

export function getSeverityBadgeColor(severity: string): string {
  const colors: Record<string, string> = {
    critical: 'bg-red-600',
    high: 'bg-orange-500',
    medium: 'bg-yellow-500',
    low: 'bg-cyan-500',
  }
  return colors[severity] || 'bg-gray-500'
}

export function getStatusColor(status: string): string {
  const colors: Record<string, string> = {
    open: 'text-red-600 bg-red-100',
    acknowledged: 'text-blue-600 bg-blue-100',
    investigating: 'text-purple-600 bg-purple-100',
    resolved: 'text-green-600 bg-green-100',
    false_positive: 'text-gray-600 bg-gray-100',
  }
  return colors[status] || 'text-gray-600 bg-gray-100'
}

export function formatDeviation(value: number, multiplier: number): string {
  if (multiplier >= 2) {
    return `${multiplier.toFixed(1)}x`
  }
  if (value >= 100) {
    return `+${value.toFixed(0)}%`
  }
  if (value <= -50) {
    return `${value.toFixed(0)}%`
  }
  return `${value > 0 ? '+' : ''}${value.toFixed(0)}%`
}

export function getTimeRanges() {
  const now = new Date()
  return [
    {
      label: 'Last hour',
      value: '1h',
      start: new Date(now.getTime() - 60 * 60 * 1000),
      end: now,
    },
    {
      label: 'Last 6 hours',
      value: '6h',
      start: new Date(now.getTime() - 6 * 60 * 60 * 1000),
      end: now,
    },
    {
      label: 'Last 24 hours',
      value: '24h',
      start: new Date(now.getTime() - 24 * 60 * 60 * 1000),
      end: now,
    },
    {
      label: 'Last 7 days',
      value: '7d',
      start: new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000),
      end: now,
    },
    {
      label: 'Last 30 days',
      value: '30d',
      start: new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000),
      end: now,
    },
  ]
}
