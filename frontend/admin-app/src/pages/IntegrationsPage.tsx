import { useEffect, useState } from 'react'
import { PageStatus } from '@oneirodex/ui'
import { getJson } from '../api/adminApi'
import { Page } from '../components/Page'
import { INTEGRATION_SECTIONS } from '../components/navConfig'
import { RailIcon } from '../components/railIcons'
import { RetroAchievementsSettingsPanel } from '../components/RetroAchievementsSettingsPanel'

const INVENTORY_CATEGORY_ORDER = [
  'metadata',
  'artwork',
  'email',
  'auth',
  'support',
  'social',
  'rtc',
  'acquire',
  'ownership',
]

const INVENTORY_CATEGORY_LABELS: Record<string, string> = {
  metadata: 'Metadata',
  artwork: 'Artwork',
  email: 'Email',
  auth: 'Auth / SSO',
  support: 'Support',
  social: 'Social',
  rtc: 'Voice / RTC',
  acquire: 'Acquire',
  ownership: 'Ownership',
}

interface InventoryRow {
  id?: string
  name?: string
  category?: string
  status?: string
  configured?: boolean
  notes?: string
  settings_href?: string
  admin_href?: string
}

interface InventoryGroup {
  id: string
  label: string
  rows: InventoryRow[]
}

function groupInventoryByCategory(rows: InventoryRow[]): InventoryGroup[] {
  const groups = new Map<string, InventoryRow[]>()
  for (const row of rows) {
    const key = row.category || 'other'
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(row)
  }
  const ordered = INVENTORY_CATEGORY_ORDER.filter((id) => groups.has(id)).map((id) => ({
    id,
    label: INVENTORY_CATEGORY_LABELS[id] || id,
    rows: groups.get(id)!,
  }))
  for (const [id, groupRows] of groups) {
    if (!INVENTORY_CATEGORY_ORDER.includes(id)) {
      ordered.push({ id, label: INVENTORY_CATEGORY_LABELS[id] || id, rows: groupRows })
    }
  }
  return ordered
}

function inventoryHref(row: InventoryRow): string {
  return row.settings_href || row.admin_href || '/admin/integrations'
}

export function IntegrationsPage() {
  const [inventory, setInventory] = useState<InventoryRow[] | null>(null)
  const [inventoryError, setInventoryError] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    getJson('/api/admin/integrations/inventory')
      .then((data) => {
        if (!controller.signal.aborted) {
          setInventory(Array.isArray(data?.integrations) ? data.integrations : [])
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setInventoryError(true)
        }
      })
    return () => controller.abort()
  }, [])

  const inventoryGroups = inventory ? groupInventoryByCategory(inventory) : []

  return (
    <Page
      title="Integrations"
      lede="Services Oneirodex talks to — metadata and art, store ownership, mail, SSO and voice, and acquisition. Same layout as Settings."
    >
      {/* Same sheet as Settings: grouped rows, one icon per row. The row id is
          the fragment its deep link names (`/admin/integrations#oidc`) — the
          anchors the nav links to must exist or the click lands at the top and
          looks like it did nothing (W27-A8). */}
      <div className="od-admin-panel od-settings">
        {INTEGRATION_SECTIONS.map((group) => (
          <section key={group.id} className="od-settings-group">
            <h2 className="od-settings-group__title">
              <RailIcon name={group.icon} size={16} /> {group.title}
            </h2>
            <ul className="od-settings-list">
              {group.items.map((item) => (
                <li
                  key={item.to}
                  id={item.to.split('#')[1]}
                >
                  <a className="od-settings-row" href={item.to}>
                    <span className="od-settings-row__title">
                      <RailIcon name={item.icon} size={16} /> {item.title}
                    </span>
                    <span className="od-settings-row__blurb">{item.blurb}</span>
                  </a>
                </li>
              ))}
            </ul>
            {group.id === 'metadata' ? (
              <div className="od-admin-inventory__group">
                <h3 className="od-admin-inventory__category">Artwork &amp; secondary</h3>
                <RetroAchievementsSettingsPanel />
              </div>
            ) : null}
          </section>
        ))}
      </div>

      {!inventory && !inventoryError ? (
        <div className="od-admin-panel od-admin-inventory od-admin-panel--stacked">
          <PageStatus loading loadingMessage="Loading provider inventory…" />
        </div>
      ) : null}

      {inventory && inventory.length > 0 ? (
        <div className="od-admin-panel od-admin-inventory od-admin-panel--stacked">
          <h2>Provider inventory</h2>
          <p>Live status of every provider, with a link to its settings.</p>
          {inventoryGroups.map((group) => (
            <div key={group.id} className="od-admin-inventory__group">
              <h3 className="od-admin-inventory__category">{group.label}</h3>
              <ul className="od-admin-inventory__list" aria-label={`${group.label} integrations`}>
                {group.rows.map((row) => (
                  <li key={row.id || row.name}>
                    <a href={inventoryHref(row)}>{row.name}</a>
                    {' — '}
                    <span className="od-admin-inventory__status">
                      {row.status || (row.configured ? 'configured' : 'available')}
                    </span>
                    {row.notes ? (
                      <span className="od-admin-inventory__notes"> · {row.notes}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      ) : null}

      {inventory && inventory.length === 0 && !inventoryError ? (
        <div className="od-admin-panel od-admin-panel--stacked">
          <p>Provider inventory returned no rows — use the list above.</p>
        </div>
      ) : null}

      {inventoryError ? (
        <div className="od-admin-panel od-admin-panel--stacked">
          <PageStatus emptyMessage="Provider inventory unavailable — use the list above." />
        </div>
      ) : null}
    </Page>
  )
}
