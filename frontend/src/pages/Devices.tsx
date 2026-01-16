import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Server, Search, Filter, ChevronLeft, ChevronRight } from 'lucide-react'
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
import { formatRelativeTime, formatBytes } from '@/lib/utils'

export function Devices() {
  const { selectedSiteId } = useSite()
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [subnetFilter, setSubnetFilter] = useState<string>('all')

  const { data, isLoading } = useQuery({
    queryKey: ['devices', selectedSiteId, page, search, subnetFilter],
    queryFn: () => api.getAssets(selectedSiteId!, {
      search: search || undefined,
      subnet: subnetFilter !== 'all' ? subnetFilter : undefined,
    }, page, 20),
    enabled: !!selectedSiteId,
  })

  const { data: subnets } = useQuery({
    queryKey: ['subnets', selectedSiteId],
    queryFn: () => api.getSubnets(selectedSiteId!),
    enabled: !!selectedSiteId,
  })

  if (!selectedSiteId) {
    return (
      <div className="flex h-[50vh] items-center justify-center">
        <div className="text-center">
          <Server className="mx-auto h-12 w-12 text-muted-foreground" />
          <h2 className="mt-4 text-lg font-semibold">No Site Selected</h2>
          <p className="text-muted-foreground">
            Please select a site to view devices.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Devices</h1>
          <p className="text-muted-foreground">
            {data?.total || 0} devices monitored
          </p>
        </div>
      </div>

      {/* Filters */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <Filter className="h-4 w-4" />
            Filters
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-4">
            <div className="flex-1 min-w-[200px]">
              <label className="text-sm text-muted-foreground mb-1 block">
                Search
              </label>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  placeholder="IP address, hostname, or MAC..."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="pl-9"
                />
              </div>
            </div>

            <div className="w-48">
              <label className="text-sm text-muted-foreground mb-1 block">
                Subnet
              </label>
              <Select value={subnetFilter} onValueChange={setSubnetFilter}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Subnets</SelectItem>
                  {subnets?.map((subnet: string) => (
                    <SelectItem key={subnet} value={subnet}>
                      {subnet}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Devices Table */}
      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>IP Address</TableHead>
                <TableHead>Hostname</TableHead>
                <TableHead>MAC Address</TableHead>
                <TableHead>Subnet</TableHead>
                <TableHead>Last Seen</TableHead>
                <TableHead>Active Alerts</TableHead>
                <TableHead></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center py-8">
                    Loading...
                  </TableCell>
                </TableRow>
              ) : data?.items?.length ? (
                data.items.map((device) => (
                  <TableRow key={device.id}>
                    <TableCell>
                      <span className="font-mono">{device.ip_address}</span>
                    </TableCell>
                    <TableCell>
                      {device.hostname || (
                        <span className="text-muted-foreground">Unknown</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <span className="font-mono text-sm">
                        {device.mac_address || '-'}
                      </span>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">{device.subnet}</Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatRelativeTime(device.last_seen)}
                    </TableCell>
                    <TableCell>
                      {device.active_alerts > 0 ? (
                        <Badge variant="critical">{device.active_alerts}</Badge>
                      ) : (
                        <span className="text-muted-foreground">0</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <Link to={`/devices/${device.id}`}>
                        <Button variant="ghost" size="sm">
                          View
                        </Button>
                      </Link>
                    </TableCell>
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={7} className="text-center py-8">
                    No devices found
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Pagination */}
      {data && data.pages > 1 && (
        <div className="flex items-center justify-between">
          <p className="text-sm text-muted-foreground">
            Page {page} of {data.pages}
          </p>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
            >
              <ChevronLeft className="h-4 w-4" />
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.min(data.pages, p + 1))}
              disabled={page === data.pages}
            >
              Next
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
