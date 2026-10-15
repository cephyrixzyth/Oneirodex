import { useEffect, useState } from 'react'
import { Button, PageStatus } from '@oneirodex/ui'
import { getJson } from '../api/adminApi'
import { DataTable } from '../components/DataTable'
import { Page } from '../components/Page'

export function PluginsPage() {
  const [plugins, setPlugins] = useState<any[]>([])
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let cancelled = false
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    getJson('/api/plugins', { signal: controller.signal })
      .then((data) => {
        if (!Array.isArray(data.plugins))
          throw new Error('Plugin registry returned an invalid response.')
        if (!cancelled) setPlugins(data.plugins)
      })
      .catch((err) => {
        if (!cancelled) setError(err)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [reloadKey])

  return (
    <Page
      title="Plugins & connectors"
      lede="Built-in registry of metadata, acquire, emu, and export hooks."
    >
      <PageStatus error={error} errorMessage="Unable to load plugins." />
      {error ? (
        <Button disabled={loading} onClick={() => setReloadKey((key) => key + 1)}>
          Retry loading plugins
        </Button>
      ) : null}
      <div className="od-admin-panel">
        {loading ? (
          <PageStatus loading loadingMessage="Loading plugins…" />
        ) : !error ? (
          // Category and status are exactly what someone comes here to group
          // by, so this is the table that most wanted sorting and had none.
          <DataTable
            caption="Registered plugins and connectors"
            scrollLabel="Plugins and connectors table"
            rows={plugins}
            getRowKey={(plugin) => plugin.id}
            emptyMessage="No plugins registered."
            initialSort={{ key: 'category', dir: 'asc' }}
            dense
            columns={[
              {
                key: 'id',
                label: 'ID',
                render: (plugin) => <code>{plugin.id}</code>,
              },
              { key: 'name', label: 'Name' },
              { key: 'category', label: 'Category' },
              { key: 'status', label: 'Status' },
            ]}
          />
        ) : null}
      </div>
    </Page>
  )
}
