import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Button, PageStatus, confirmAction, errorFromBody } from '@oneirodex/ui'
import { csrfHeaders, deleteJson, getJson } from '../api/adminApi'
import { Page } from '../components/Page'
import { DataTable } from '../components/DataTable'
import { errorText } from '../utils/errorText'
import { showToast } from '../utils/toast'

type Emoji = { id: number; slug: string; label: string; emoji: string; url: string }
const API = '/api/admin/chat-emoji'
export function ChatEmojiPage() {
  const [emojis, setEmojis] = useState<Emoji[]>([])
  const [maxCustom, setMaxCustom] = useState(20)
  const [maxBytes, setMaxBytes] = useState(256 * 1024)
  const [maxEdge, setMaxEdge] = useState(128)
  const [slug, setSlug] = useState('')
  const [label, setLabel] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadFailed, setLoadFailed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [reload, setReload] = useState(0)
  const fileRef = useRef<HTMLInputElement>(null)
  const lock = useRef(false)
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setLoadFailed(false)
    setError('')
    getJson(API)
      .then((data) => {
        if (cancelled) return
        if (!Array.isArray(data.emojis))
          throw new Error('Custom emoji returned an invalid response.')
        setEmojis(data.emojis)
        setMaxCustom(data.max_custom)
        setMaxBytes(data.limits.max_upload_bytes)
        setMaxEdge(data.limits.max_edge_px)
      })
      .catch((err) => {
        if (!cancelled) {
          setError(errorText(err))
          setLoadFailed(true)
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [reload])
  async function upload(event: FormEvent) {
    event.preventDefault()
    if (loading || loadFailed || lock.current || !file || emojis.length >= maxCustom) return
    if (file.size > maxBytes) {
      setError(`Image must be at most ${maxBytes / 1024} KB.`)
      return
    }
    lock.current = true
    setBusy(true)
    setError('')
    setMessage('')
    try {
      const body = new FormData()
      body.set('slug', slug)
      body.set('label', label)
      body.set('file', file)
      const response = await fetch(API, {
        method: 'POST',
        credentials: 'same-origin',
        headers: csrfHeaders(),
        body,
      })
      const data = await response.json()
      if (!response.ok || data.ok === false)
        throw errorFromBody(data, response.status, 'Emoji upload')
      if (!data.emoji) throw new Error('Custom emoji upload returned an invalid response.')
      setEmojis((rows) => [...rows, data.emoji])
      setSlug('')
      setLabel('')
      setFile(null)
      if (fileRef.current) fileRef.current.value = ''
      setMessage('Custom emoji uploaded.')
      showToast('Custom emoji uploaded.', 'success')
    } catch (err) {
      const text = errorText(err) || 'Could not upload custom emoji.'
      setError(text)
      showToast(text, 'error')
    } finally {
      lock.current = false
      setBusy(false)
    }
  }
  async function remove(row: Emoji) {
    if (busy || lock.current) return
    lock.current = true
    const confirmed = await confirmAction({
      title: 'Delete custom emoji?',
      body: `Remove ${row.emoji} from household chat reactions?`,
      confirmLabel: 'Delete emoji',
      cancelLabel: 'Keep emoji',
    })
    if (!confirmed) {
      lock.current = false
      return
    }
    setBusy(true)
    setError('')
    setMessage('')
    try {
      await deleteJson(`${API}/${encodeURIComponent(row.slug)}`)
      setEmojis((rows) => rows.filter((emoji) => emoji.slug !== row.slug))
      setMessage('Custom emoji deleted.')
      showToast('Custom emoji deleted.', 'success')
    } catch (err) {
      const text = errorText(err) || 'Could not delete custom emoji.'
      setError(text)
      showToast(text, 'error')
    } finally {
      lock.current = false
      setBusy(false)
    }
  }
  return (
    <Page title="Household chat emoji" lede="Add custom reaction images for household chat.">
      <PageStatus loading={loading} loadingMessage="Loading custom emoji…" error={error || null} />
      {loadFailed ? (
        <Button onClick={() => setReload((value) => value + 1)}>Retry loading emoji</Button>
      ) : null}
      {!loading ? (
        <>
          <form className="od-admin-panel" onSubmit={upload}>
            <fieldset
              className="od-admin-fieldset"
              disabled={busy || loadFailed || emojis.length >= maxCustom}
            >
              <legend>Upload custom emoji</legend>
              <label className="od-admin-field">
                Slug
                <input
                  className="od-admin-input"
                  required
                  pattern="[a-z0-9_-]{2,24}"
                  minLength={2}
                  maxLength={24}
                  value={slug}
                  onChange={(e) => setSlug(e.target.value)}
                />
              </label>
              <p className="od-admin-hint">
                Use 2–24 lowercase letters, digits, underscores or hyphens.
              </p>
              <label className="od-admin-field">
                Label
                <input
                  className="od-admin-input"
                  maxLength={64}
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                />
              </label>
              <label className="od-admin-field">
                Image
                <input
                  ref={fileRef}
                  className="od-admin-input"
                  type="file"
                  required
                  accept=".png,.webp,.jpg,.jpeg,image/png,image/webp,image/jpeg"
                  onChange={(e) => setFile(e.target.files?.[0] || null)}
                />
              </label>
              <p className="od-admin-hint">
                PNG, WebP or JPEG; up to {maxBytes / 1024} KB. Images are resized to fit {maxEdge}{' '}
                px and stored as WebP.
              </p>
            </fieldset>
            <Button
              variant="primary"
              type="submit"
              disabled={busy || loadFailed || emojis.length >= maxCustom}
            >
              {busy ? 'Working…' : 'Upload emoji'}
            </Button>
            {emojis.length >= maxCustom ? (
              <p className="od-admin-hint">
                The {maxCustom}-emoji limit is reached. Delete an installed emoji to add another.
              </p>
            ) : null}
          </form>
          {message ? (
            <PageStatus announcement="status" className="od-admin-hint">
              {message}
            </PageStatus>
          ) : null}
          {!loadFailed ? (
            <section className="od-admin-panel">
              <h2>
                Installed ({emojis.length} / {maxCustom})
              </h2>
              <DataTable
                caption="Installed household emoji"
                scrollLabel="Custom emoji table"
                rows={emojis}
                getRowKey={(row) => row.id}
                emptyMessage="No custom emoji yet."
                initialSort={{ key: 'slug', dir: 'asc' }}
                columns={[
                  {
                    key: 'preview',
                    label: 'Preview',
                    sortable: false,
                    filterable: false,
                    render: (row) => <img src={row.url} alt={row.label} width={28} height={28} />,
                  },
                  { key: 'slug', label: 'Reaction', render: (row) => <code>{row.emoji}</code> },
                  { key: 'label', label: 'Label' },
                  {
                    key: 'actions',
                    label: 'Actions',
                    sortable: false,
                    filterable: false,
                    render: (row) => (
                      <Button
                        size="sm"
                        variant="danger"
                        disabled={busy}
                        aria-label={`Delete ${row.emoji}`}
                        onClick={() => remove(row)}
                      >
                        Delete
                      </Button>
                    ),
                  },
                ]}
              />
            </section>
          ) : null}
          <a className="od-cbtn" href="/admin/integrations">
            Back to Integrations
          </a>
        </>
      ) : null}
    </Page>
  )
}
