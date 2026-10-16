import { useEffect, useState, type FormEvent } from 'react'
import { useParams } from 'react-router-dom'
import { Button, PageStatus } from '@oneirodex/ui'
import { getJson, csrfToken, putForm } from '../api/adminApi'
import { Page } from '../components/Page'
import './LibraryEditorPage.css'

type LibraryEditorModel = {
  uuid: string
  name: string
  platform: string
  scan_depth: number
  watch_enabled: boolean | null
  image_url?: string
}

type Platform = { key: string; label: string }

export function LibraryEditorPage() {
  const { libraryUuid = '' } = useParams()
  const [library, setLibrary] = useState<LibraryEditorModel | null>(null)
  const [platforms, setPlatforms] = useState<Platform[]>([])
  const [name, setName] = useState('')
  const [platform, setPlatform] = useState('')
  const [depth, setDepth] = useState('1')
  const [watch, setWatch] = useState('default')
  const [image, setImage] = useState<File | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [saved, setSaved] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    Promise.all([
      getJson(`/api/admin/libraries/${encodeURIComponent(libraryUuid)}`, {
        signal: controller.signal,
      }),
      getJson('/api/admin/library_platforms', { signal: controller.signal }),
    ])
      .then(([row, platformData]) => {
        const options = Array.isArray(platformData?.platforms) ? platformData.platforms : []
        setLibrary(row)
        setName(String(row?.name || ''))
        setPlatform(String(row?.platform || ''))
        setDepth(String(row?.scan_depth || 1))
        setWatch(row?.watch_enabled == null ? 'default' : row.watch_enabled ? 'on' : 'off')
        setPlatforms(options)
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setError(reason)
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [libraryUuid])

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (saving) return
    setSaving(true)
    setSaved(false)
    setError(null)
    try {
      const body = new FormData()
      body.append('csrf_token', csrfToken())
      body.append('name', name.trim())
      body.append('platform', platform)
      body.append('scan_depth', depth)
      body.append('watch_enabled', watch)
      if (image) body.append('image', image, image.name)
      const updated = await putForm<LibraryEditorModel>(
        `/api/admin/libraries/${encodeURIComponent(libraryUuid)}`,
        body,
      )
      setLibrary(updated)
      setName(String(updated?.name || ''))
      setPlatform(String(updated?.platform || ''))
      setDepth(String(updated?.scan_depth || 1))
      setWatch(updated?.watch_enabled == null ? 'default' : updated.watch_enabled ? 'on' : 'off')
      setImage(null)
      setSaved(true)
    } catch (reason) {
      setError(reason)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Page
      title="Edit library"
      lede="Update the library name, platform, scan depth, watch preference, or hero image."
    >
      <div className="od-admin-panel__toolbar">
        <a className="od-cbtn" href="/libraries">
          Back to libraries
        </a>
      </div>
      <PageStatus
        loading={loading}
        loadingMessage="Loading library…"
        error={error}
        errorMessage="Unable to load or save this library."
      />
      {saved ? (
        <PageStatus announcement="status" className="od-admin-status">
          Library saved.
        </PageStatus>
      ) : null}
      {library && !loading ? (
        <form className="od-admin-panel od-library-editor" onSubmit={(event) => void save(event)}>
          <label className="od-admin-field">
            Library name
            <input
              className="od-admin-input"
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
              maxLength={255}
            />
          </label>
          <label className="od-admin-field">
            Platform
            <select
              className="od-admin-input"
              value={platform}
              onChange={(event) => setPlatform(event.target.value)}
              required
            >
              {platforms.map((item) => (
                <option key={item.key} value={item.key}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label className="od-admin-field">
            Scan depth
            <select
              className="od-admin-input"
              value={depth}
              onChange={(event) => setDepth(event.target.value)}
            >
              <option value="1">1 — games directly under the scan root</option>
              <option value="2">2 — letter buckets then game folders</option>
            </select>
          </label>
          <label className="od-admin-field">
            Update library when folders change
            <select
              className="od-admin-input"
              value={watch}
              onChange={(event) => setWatch(event.target.value)}
            >
              <option value="default">Follow global setting</option>
              <option value="on">Prefer watch when the global switch is on</option>
              <option value="off">Opt out</option>
            </select>
          </label>
          {library.image_url ? (
            <img src={library.image_url} alt="Current library image" width={120} height={120} />
          ) : null}
          <label className="od-admin-field">
            Replace library image
            <input
              className="od-admin-input"
              type="file"
              accept="image/png,image/jpeg,image/gif,image/webp"
              onChange={(event) => setImage(event.target.files?.[0] || null)}
            />
            <span className="od-admin-hint">JPG, PNG, GIF, or WebP; up to 10 MB.</span>
          </label>
          <Button type="submit" variant="primary" disabled={saving || !platform}>
            {saving ? 'Saving…' : 'Save library'}
          </Button>
        </form>
      ) : null}
    </Page>
  )
}
