import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Shield,
  Plus,
  Pencil,
  Trash2,
  ToggleLeft,
  ToggleRight,
  AlertTriangle,
  AlertCircle,
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useSite } from '@/hooks/useSite'
import api from '@/lib/api'
import type { AlertRule } from '@/types'

const RULE_TYPES = [
  { value: 'threshold', label: 'Threshold' },
  { value: 'persistence', label: 'Persistence' },
  { value: 'rate', label: 'Rate Change' },
  { value: 'baseline', label: 'Baseline Deviation' },
]

const SEVERITIES = ['critical', 'high', 'medium', 'low']

export function Rules() {
  const { selectedSiteId } = useSite()
  const queryClient = useQueryClient()
  const [isCreating, setIsCreating] = useState(false)
  const [editingRule, setEditingRule] = useState<AlertRule | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Clear error after 5 seconds
  useEffect(() => {
    if (error) {
      const timer = setTimeout(() => setError(null), 5000)
      return () => clearTimeout(timer)
    }
  }, [error])

  const { data: rules, isLoading } = useQuery({
    queryKey: ['rules', selectedSiteId],
    queryFn: () => api.getRules(selectedSiteId!),
    enabled: !!selectedSiteId,
  })

  const createMutation = useMutation({
    mutationFn: (rule: Partial<AlertRule>) => api.createRule(selectedSiteId!, rule),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['rules', selectedSiteId] })
      setIsCreating(false)
      setError(null)
    },
    onError: (err: Error) => {
      console.error('Failed to create rule:', err)
      setError(`Failed to create rule: ${err.message}`)
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, rule }: { id: string; rule: Partial<AlertRule> }) =>
      api.updateRule(id, rule),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['rules', selectedSiteId] })
      setEditingRule(null)
      setError(null)
    },
    onError: (err: Error) => {
      console.error('Failed to update rule:', err)
      setError(`Failed to update rule: ${err.message}`)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteRule(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['rules', selectedSiteId] })
    },
    onError: (err: Error) => {
      console.error('Failed to delete rule:', err)
      setError(`Failed to delete rule: ${err.message}`)
    },
  })

  const toggleMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      api.updateRule(id, { enabled }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['rules', selectedSiteId] })
    },
    onError: (err: Error) => {
      console.error('Failed to toggle rule:', err)
      setError(`Failed to toggle rule: ${err.message}`)
    },
  })

  if (!selectedSiteId) {
    return (
      <div className="flex h-[50vh] items-center justify-center">
        <div className="text-center">
          <Shield className="mx-auto h-12 w-12 text-muted-foreground" />
          <h2 className="mt-4 text-lg font-semibold">No Site Selected</h2>
          <p className="text-muted-foreground">
            Please select a site to manage rules.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Alert Rules</h1>
          <p className="text-muted-foreground">
            Configure thresholds and conditions for generating alerts
          </p>
        </div>
        <Button onClick={() => setIsCreating(true)} disabled={isCreating}>
          <Plus className="mr-2 h-4 w-4" />
          Add Rule
        </Button>
      </div>

      {/* Error Display */}
      {error && (
        <div className="flex items-center gap-2 p-4 rounded-lg bg-destructive/10 text-destructive border border-destructive/20">
          <AlertCircle className="h-5 w-5 flex-shrink-0" />
          <p className="text-sm">{error}</p>
        </div>
      )}

      {/* Create/Edit Form */}
      {(isCreating || editingRule) && (
        <RuleForm
          rule={editingRule}
          onSubmit={(rule) => {
            if (editingRule) {
              updateMutation.mutate({ id: editingRule.id, rule })
            } else {
              createMutation.mutate(rule)
            }
          }}
          onCancel={() => {
            setIsCreating(false)
            setEditingRule(null)
          }}
          isLoading={createMutation.isPending || updateMutation.isPending}
        />
      )}

      {/* Rules Table */}
      <Card>
        <CardHeader>
          <CardTitle>Active Rules</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Condition</TableHead>
                <TableHead>Severity</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center py-8">
                    Loading...
                  </TableCell>
                </TableRow>
              ) : rules?.length ? (
                rules.map((rule) => (
                  <TableRow key={rule.id}>
                    <TableCell>
                      <div>
                        <p className="font-medium">{rule.name}</p>
                        {rule.description && (
                          <p className="text-sm text-muted-foreground">
                            {rule.description}
                          </p>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className="capitalize">
                        {rule.rule_type}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <code className="text-sm bg-muted px-2 py-1 rounded">
                        {formatCondition(rule)}
                      </code>
                    </TableCell>
                    <TableCell>
                      <Badge variant={rule.severity as 'critical' | 'high' | 'medium' | 'low'}>
                        {rule.severity}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <button
                        onClick={() =>
                          toggleMutation.mutate({
                            id: rule.id,
                            enabled: !rule.enabled,
                          })
                        }
                        className="flex items-center gap-2"
                      >
                        {rule.enabled ? (
                          <>
                            <ToggleRight className="h-5 w-5 text-green-500" />
                            <span className="text-sm text-green-600">Active</span>
                          </>
                        ) : (
                          <>
                            <ToggleLeft className="h-5 w-5 text-muted-foreground" />
                            <span className="text-sm text-muted-foreground">Disabled</span>
                          </>
                        )}
                      </button>
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-2">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setEditingRule(rule)}
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            if (confirm('Delete this rule?')) {
                              deleteMutation.mutate(rule.id)
                            }
                          }}
                        >
                          <Trash2 className="h-4 w-4 text-red-500" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={6} className="text-center py-8">
                    <div className="space-y-2">
                      <AlertTriangle className="mx-auto h-8 w-8 text-muted-foreground" />
                      <p>No rules configured</p>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setIsCreating(true)}
                      >
                        Create your first rule
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Default Rules Info */}
      <Card>
        <CardHeader>
          <CardTitle>System Default Rules</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground mb-4">
            The following rules are always active and cannot be disabled:
          </p>
          <div className="space-y-3">
            <div className="flex items-center justify-between p-3 bg-muted/50 rounded-lg">
              <div>
                <p className="font-medium">Critical Anomaly Detection</p>
                <p className="text-sm text-muted-foreground">
                  Score &gt;= 0.95 in a single 5-min window
                </p>
              </div>
              <Badge variant="critical">Critical</Badge>
            </div>
            <div className="flex items-center justify-between p-3 bg-muted/50 rounded-lg">
              <div>
                <p className="font-medium">High Anomaly Persistence</p>
                <p className="text-sm text-muted-foreground">
                  Score &gt;= 0.85 for 3 consecutive windows (15 min)
                </p>
              </div>
              <Badge variant="high">High</Badge>
            </div>
            <div className="flex items-center justify-between p-3 bg-muted/50 rounded-lg">
              <div>
                <p className="font-medium">Medium Anomaly Persistence</p>
                <p className="text-sm text-muted-foreground">
                  Score &gt;= 0.70 for 5 consecutive windows (25 min)
                </p>
              </div>
              <Badge variant="medium">Medium</Badge>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

function RuleForm({
  rule,
  onSubmit,
  onCancel,
  isLoading,
}: {
  rule: AlertRule | null
  onSubmit: (rule: Partial<AlertRule>) => void
  onCancel: () => void
  isLoading: boolean
}) {
  const [name, setName] = useState(rule?.name || '')
  const [description, setDescription] = useState(rule?.description || '')
  const [ruleType, setRuleType] = useState(rule?.rule_type || 'threshold')
  const [severity, setSeverity] = useState(rule?.severity || 'medium')
  const [threshold, setThreshold] = useState(rule?.config?.threshold?.toString() || '0.85')
  const [windowCount, setWindowCount] = useState(rule?.config?.window_count?.toString() || '3')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    onSubmit({
      name,
      description,
      rule_type: ruleType,
      severity,
      config: {
        threshold: parseFloat(threshold),
        window_count: parseInt(windowCount),
      },
      enabled: true,
    })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{rule ? 'Edit Rule' : 'Create New Rule'}</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <label className="text-sm font-medium">Name</label>
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Rule name"
                required
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Description</label>
              <Input
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Optional description"
              />
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">Rule Type</label>
              <Select value={ruleType} onValueChange={setRuleType}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {RULE_TYPES.map((t) => (
                    <SelectItem key={t.value} value={t.value}>
                      {t.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Severity</label>
              <Select value={severity} onValueChange={setSeverity}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SEVERITIES.map((s) => (
                    <SelectItem key={s} value={s}>
                      {s.charAt(0).toUpperCase() + s.slice(1)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Threshold</label>
              <Input
                type="number"
                step="0.01"
                min="0"
                max="1"
                value={threshold}
                onChange={(e) => setThreshold(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Window Count</label>
              <Input
                type="number"
                min="1"
                max="20"
                value={windowCount}
                onChange={(e) => setWindowCount(e.target.value)}
              />
            </div>
          </div>

          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={onCancel}>
              Cancel
            </Button>
            <Button type="submit" disabled={isLoading}>
              {isLoading ? 'Saving...' : rule ? 'Update Rule' : 'Create Rule'}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

function formatCondition(rule: AlertRule): string {
  const threshold = rule.config?.threshold || 0
  const windowCount = rule.config?.window_count || 1

  switch (rule.rule_type) {
    case 'threshold':
      return `score >= ${threshold}`
    case 'persistence':
      return `score >= ${threshold} for ${windowCount} windows`
    case 'rate':
      return `rate change > ${(threshold * 100).toFixed(0)}%`
    case 'baseline':
      return `${(threshold * 100).toFixed(0)}% deviation from baseline`
    default:
      return JSON.stringify(rule.config)
  }
}
