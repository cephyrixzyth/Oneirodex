import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Button, PageStatus } from '@oneirodex/ui'
import { deleteJson, getJson, postJson } from '../api/adminApi'
import { errorText } from '../utils/errorText'
import { MetricStrip } from '../components/opsWidgets'
import { showToast } from '../utils/toast'
import { Page } from '../components/Page'

type ExtGroupId = 'archives' | 'disc' | 'cart' | 'other'

interface ExtensionItem {
  id: string
  value: string
}

/** Capability-language hint groups for scan recognition (no Class A brands). */
export const EXT_GROUPS = [
  {
    id: 'archives',
    label: 'Archives',
    hint: 'Compressed packages scanned as game containers',
    members: ['zip', '7z', 'rar', 'gz'],
  },
  {
    id: 'disc',
    label: 'Disc images',
    hint: 'Optical, floppy, and disc dumps',
    members: ['iso', 'img', 'bin', 'dsk', 'd64', 'adf', 'cue', 'nrg', 'mdf'],
  },
  {
    id: 'cart',
    label: 'Cartridge / ROM',
    hint: 'Console and handheld ROM dumps',
    members: [
      'nes',
      'sfc',
      'smc',
      'gba',
      'gb',
      'gbc',
      'nds',
      'z64',
      'n64',
      'gen',
      'sms',
      'gg',
      '32x',
      'pce',
      'ngc',
      'a78',
      'lnx',
      'jag',
      'j64',
      'vec',
      'rom',
      'prg',
      'tap',
      'stx',
      'st',
    ],
  },
]

const API = '/api/file_types/allowed'

function normalizeExt(raw: unknown): string {
  return String(raw || '')
    .trim()
    .replace(/^\.+/, '')
    .toLowerCase()
}

function groupForValue(value: string): ExtGroupId {
  const v = normalizeExt(value)
  for (const group of EXT_GROUPS) {
    if (group.members.includes(v)) return group.id as ExtGroupId
  }
  return 'other'
}

export function ExtensionsPage() {
  const [items, setItems] = useState<ExtensionItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [filter, setFilter] = useState('')
  const [busy, setBusy] = useState(false)

  async function reload() {
    const data = await getJson(API)
    const list = Array.isArray(data) ? data : []
    setItems(
      list
        .map((row) => ({
          id: row.id,
          value: normalizeExt(row.value),
        }))
        .filter((row) => row.value)
        .sort((a, b) => a.value.localeCompare(b.value)),
    )
  }

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    reload()
      .then(() => {
        if (!cancelled) {
          setError(null)
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(errorText(err) || 'Failed to load extensions')
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const known = useMemo(() => new Set(items.map((i) => i.value)), [items])

  const filtered = useMemo(() => {
    const q = normalizeExt(filter)
    if (!q) return items
    return items.filter((i) => i.value.includes(q))
  }, [items, filter])

  // Counted from the full list, not `grouped` — that one is derived from the
  // search filter, and a summary strip that shrinks as you type would be
  // describing the search rather than the configuration.
  const totals = useMemo(() => {
    const counts: Record<ExtGroupId, number> = { archives: 0, disc: 0, cart: 0, other: 0 }
    for (const item of items) {
      counts[groupForValue(item.value)] += 1
    }
    return counts
  }, [items])

  const grouped = useMemo(() => {
    const buckets: Record<ExtGroupId, ExtensionItem[]> = {
      archives: [],
      disc: [],
      cart: [],
      other: [],
    }
    for (const item of filtered) {
      buckets[groupForValue(item.value)].push(item)
    }
    return buckets
  }, [filtered])

  const suggestions = useMemo(() => {
    const out: { value: string; groupId: string; groupLabel: string }[] = []
    for (const group of EXT_GROUPS) {
      for (const member of group.members) {
        if (!known.has(member)) {
          out.push({ value: member, groupId: group.id, groupLabel: group.label })
        }
      }
    }
    return out.slice(0, 12)
  }, [known])

  async function addExtension(raw: unknown) {
    const value = normalizeExt(raw)
    if (!value || busy) return
    if (known.has(value)) {
      showToast(`.${value} is already listed`, 'warn')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await postJson(API, { value })
      await reload()
      setDraft('')
      showToast(`Added .${value}`, 'success')
    } catch (err) {
      const msg = errorText(err) || 'Add failed'
      setError(msg)
      showToast(msg, 'error')
    } finally {
      setBusy(false)
    }
  }

  async function removeExtension(item: ExtensionItem | null | undefined) {
    if (!item?.id || busy) return
    setBusy(true)
    setError(null)
    try {
      await deleteJson(API, { id: item.id })
      await reload()
      showToast(`Removed .${item.value}`, 'success')
    } catch (err) {
      const msg = errorText(err) || 'Remove failed'
      setError(msg)
      showToast(msg, 'error')
    } finally {
      setBusy(false)
    }
  }

  function onAddSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    addExtension(draft)
  }

  if (loading) {
    return (
      <Page title="File Extensions">
        <PageStatus loading loadingMessage="Loading allowed extensions…" />
      </Page>
    )
  }

  if (error && items.length === 0) {
    return (
      <Page title="File Extensions">
        <PageStatus error={error} />
        <a className="od-btn" href="/libraries">
          Back to libraries
        </a>
      </Page>
    )
  }

  const sections = [
    ...EXT_GROUPS.map((g) => ({ ...g, rows: grouped[g.id as ExtGroupId] || [] })),
    {
      id: 'other',
      label: 'Other',
      hint: 'Extensions not in the common archive / disc / cart hints',
      rows: grouped.other || [],
    },
  ]

  return (
    <Page
      title="File Extensions"
      className="od-ext-page"
      lede={
        <>
          Extensions used during library scan recognition. Only files matching these suffixes are
          treated as games when scanning folders — add archives, disc images, or cartridge dumps
          your libraries actually contain.
        </>
      }
    >
      {/* UID-014. An empty extension list is the state worth shouting about:
          scans would recognise nothing at all, and the page otherwise reports
          that as a quiet "0" in a table. */}
      <MetricStrip
        label="Extensions"
        items={[
          {
            id: 'total',
            label: 'Extensions',
            value: items.length,
            hint: 'recognised on scan',
            tone: items.length === 0 ? 'action' : 'good',
          },
          { id: 'archives', label: 'Archives', value: totals.archives, tone: 'info' },
          { id: 'disc', label: 'Disc images', value: totals.disc, tone: 'info' },
          { id: 'cart', label: 'Cartridge', value: totals.cart, tone: 'info' },
        ]}
      />

      {/* A failure after the list has loaded — the page still works, but this
          is an error and now says so assertively rather than politely. */}
      <PageStatus error={error} />

      <form className="od-admin-panel od-ext-add" onSubmit={onAddSubmit}>
        <div className="od-admin-actions-row od-admin-actions-row--end od-admin-actions-row--flush">
          <label className="od-admin-field od-admin-field--grow od-admin-field--flush">
            Add extension
            <input
              className="od-admin-input"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="zip"
              maxLength={10}
              aria-label="File extension to add"
              disabled={busy}
              autoComplete="off"
              spellCheck={false}
            />
          </label>
          <Button type="submit" disabled={busy || !normalizeExt(draft)}>
            Add
          </Button>
          <label className="od-admin-field od-admin-field--grow-sm od-admin-field--flush">
            Filter
            <input
              className="od-admin-input"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Search…"
              aria-label="Filter extensions"
              autoComplete="off"
              spellCheck={false}
            />
          </label>
        </div>
        <p className="od-admin-lede od-admin-lede--flush" aria-live="polite">
          {items.length
            ? `${items.length} allowed · changes apply immediately to the next scan`
            : 'No extensions yet — add at least one so the scanner knows what counts as a game'}
        </p>
      </form>

      {items.length === 0 ? (
        <PageStatus
          className="od-ext-empty"
          emptyMessage="Empty list — library scans will not recognize any files until you add extensions."
        />
      ) : null}

      {suggestions.length && items.length > 0 ? (
        <div className="od-admin-panel od-ext-suggestions">
          <h2 className="od-admin-panel-title">Quick add</h2>
          <p className="od-admin-lede">
            Common scan suffixes not yet in your list (capability hints only).
          </p>
          <div className="od-ext-chip-row" role="list">
            {suggestions.map((s) => (
              <button
                key={s.value}
                type="button"
                className="od-ext-chip od-ext-chip--suggest"
                role="listitem"
                disabled={busy}
                onClick={() => addExtension(s.value)}
                title={`Add .${s.value} (${s.groupLabel})`}
              >
                .{s.value}
                <span className="od-ext-chip__action" aria-hidden="true">
                  +
                </span>
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {sections.map((section) => {
        if (!section.rows.length && section.id === 'other') return null
        if (!section.rows.length && filter) return null
        if (!section.rows.length) return null
        return (
          <section key={section.id} className="od-admin-panel od-ext-group">
            <header className="od-ext-group__head">
              <h2 className="od-admin-panel-title">{section.label}</h2>
              <p className="od-admin-lede od-admin-lede--flush">{section.hint}</p>
            </header>
            <div className="od-ext-chip-row" role="list">
              {section.rows.map((item: ExtensionItem) => (
                <span key={item.id} className="od-ext-chip" role="listitem">
                  <span className="od-ext-chip__label">.{item.value}</span>
                  <button
                    type="button"
                    className="od-ext-chip__remove"
                    aria-label={`Remove .${item.value}`}
                    disabled={busy}
                    onClick={() => removeExtension(item)}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          </section>
        )
      })}

      {filter && filtered.length === 0 && items.length > 0 ? (
        <PageStatus emptyMessage={`No extensions match “${filter}”.`} />
      ) : null}

      <div className="od-admin-actions-row">
        <a className="od-btn" href="/libraries">
          Libraries
        </a>
        <a className="od-btn od-btn--ghost" href="/scan_management">
          Scan jobs
        </a>
      </div>
    </Page>
  )
}
