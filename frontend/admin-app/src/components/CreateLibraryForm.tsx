import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { Button, PageStatus } from '@oneirodex/ui'
import { getJson, postForm } from '../api/adminApi'
import { queueLeafScan } from '../api/proposeLeafLibrariesApi'
import { errorText } from '../utils/errorText'
import { showToast } from '../utils/toast'
import { LibraryImageCropper } from './LibraryImageCropper'
import { ServerFolderBrowser } from './ServerFolderBrowser'
import './CreateLibraryForm.css'

interface PlatformOption {
  key: string
  label: string
}

/** A direct, single-library path through the same create + first-scan contract as bulk import. */
export function CreateLibraryForm({
  onCreated,
  onComplete,
}: {
  onCreated?: () => void
  onComplete?: () => void
}) {
  const [platforms, setPlatforms] = useState<PlatformOption[]>([])
  const [platformError, setPlatformError] = useState<unknown>(null)
  const [name, setName] = useState('')
  const [path, setPath] = useState('')
  const [platform, setPlatform] = useState('')
  const [scanMode, setScanMode] = useState<'folders' | 'files'>('folders')
  const scanPath = path.trim()
  const [depth, setDepth] = useState<1 | 2>(1)
  const [watch, setWatch] = useState('default')
  const [image, setImage] = useState<File | null>(null)
  const [pendingImage, setPendingImage] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<{ note?: string } | null>(null)
  const [browseOpen, setBrowseOpen] = useState(false)
  const imageInputRef = useRef<HTMLInputElement | null>(null)
  const imagePreviewUrl = useMemo(() => (image ? URL.createObjectURL(image) : ''), [image])

  useEffect(
    () => () => {
      if (imagePreviewUrl) URL.revokeObjectURL(imagePreviewUrl)
    },
    [imagePreviewUrl],
  )

  useEffect(() => {
    const controller = new AbortController()
    getJson('/api/admin/library_platforms', { signal: controller.signal })
      .then((data) => {
        const payload = Array.isArray(data) ? data : data?.platforms
        const options = Array.isArray(payload) ? payload : []
        setPlatforms(options)
        setPlatform((current) => current || options[0]?.key || '')
      })
      .catch((err) => {
        if (!controller.signal.aborted) setPlatformError(err)
      })
    return () => controller.abort()
  }, [])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !name.trim() || !platform) return
    setBusy(true)
    setError('')
    setResult(null)
    let uuid = ''
    try {
      const body = new FormData()
      body.append('name', name.trim())
      body.append('platform', platform)
      body.append('scan_depth', String(depth))
      body.append('watch_enabled', watch)
      if (image) body.append('image', image, image.name)
      const created = await postForm<{ library_uuid?: string }>('/api/admin/libraries', body)
      uuid = String(created.library_uuid || '')
      if (!uuid) throw new Error('Library was created but its ID was not returned.')
    } catch (err) {
      setError(errorText(err) || 'Library could not be created.')
      setBusy(false)
      return
    }

    setName('')
    setPath('')
    setImage(null)
    onCreated?.()
    if (!scanPath) {
      const note = 'Library created. Add a folder path when you are ready to scan.'
      setResult({ note })
      setBusy(false)
      if (onComplete) {
        showToast(note, 'success')
        onComplete()
      }
      return
    }

    let scanQueued = false
    try {
      const scan = await queueLeafScan({ uuid, path: scanPath, scan_mode: scanMode })
      if (!scan.ok) {
        setError(`Library created, but the first scan could not be queued: ${scan.error}`)
      } else {
        const note = scan.data?.message || 'Library created and first scan queued.'
        setResult({ note })
        if (onComplete) showToast(note, 'success')
        scanQueued = true
      }
    } catch (err) {
      setError(
        `Library created, but first scan could not be queued: ${errorText(err) || 'request failed.'}`,
      )
    } finally {
      setBusy(false)
      if (scanQueued) onComplete?.()
    }
  }

  return (
    <section className="od-admin-panel od-create-library" aria-labelledby="od-create-library-title">
      <div>
        <h2 id="od-create-library-title" className="od-admin-panel-title">
          Add one library
        </h2>
        <p className="od-admin-lede">
          Choose a name and platform. Add a folder path to queue the first scan now, or leave it
          blank and scan later.
        </p>
      </div>
      <PageStatus
        error={platformError || error || null}
        errorMessage={platformError ? 'Unable to load platform choices.' : error || null}
        className="od-create-library__message od-create-library__message--error"
      />
      <form className="od-create-library__form" onSubmit={(event) => void submit(event)}>
        <label className="od-admin-field">
          Library name
          <input
            className="od-admin-input"
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
            autoComplete="off"
          />
        </label>
        <label className="od-admin-field">
          Platform
          <select
            className="od-admin-input"
            required
            value={platform}
            onChange={(event) => setPlatform(event.target.value)}
            disabled={!platforms.length}
          >
            {platforms.map((item) => (
              <option key={item.key} value={item.key}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label className="od-admin-field od-create-library__path">
          Folder path inside the server (optional)
          <span className="od-create-library__path-row">
            <input
              className="od-admin-input"
              value={path}
              onChange={(event) => setPath(event.target.value)}
              placeholder="/storage/games/nes"
              autoComplete="off"
            />
            <Button type="button" className="od-btn--ghost" onClick={() => setBrowseOpen(true)}>
              Browse server
            </Button>
          </span>
        </label>
        <label className="od-admin-field">
          Folder layout
          <select
            className="od-admin-input"
            value={scanMode}
            onChange={(event) => setScanMode(event.target.value as 'folders' | 'files')}
          >
            <option value="folders">Game folders</option>
            <option value="files">Game files directly in this folder</option>
          </select>
        </label>
        <label className="od-admin-field">
          Scan depth
          <select
            className="od-admin-input"
            value={depth}
            onChange={(event) => setDepth(Number(event.target.value) as 1 | 2)}
          >
            <option value={1}>One folder deep</option>
            <option value={2}>Two folders deep</option>
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
        <label className="od-admin-field">
          Library image
          <input
            ref={imageInputRef}
            className="od-admin-input"
            type="file"
            accept=".jpg,.jpeg,.png,.gif,.webp,image/jpeg,image/png,image/gif,image/webp"
            onChange={(event) => {
              const file = event.currentTarget.files?.[0]
              event.currentTarget.value = ''
              if (!file) return
              if (file.size > 10 * 1024 * 1024) {
                setError('File is too large! Maximum size is 10MB.')
                return
              }
              setError('')
              setPendingImage(file)
            }}
          />
          <span className="od-admin-hint">Optional; JPG, PNG, GIF, or WebP up to 10 MB.</span>
        </label>
        {imagePreviewUrl ? (
          <figure className="od-create-library__image-preview">
            <img src={imagePreviewUrl} alt="Selected library image preview" />
          </figure>
        ) : null}
        <div className="od-create-library__actions">
          <Button
            type="submit"
            className="od-btn--accent"
            disabled={busy || !platforms.length || !name.trim()}
          >
            {busy
              ? scanPath
                ? 'Creating and queueing…'
                : 'Creating…'
              : scanPath
                ? 'Create library and start scan'
                : 'Create library'}
          </Button>
          <span className="od-admin-lede od-admin-lede--tight">
            {scanPath
              ? 'The scan uses the server-visible path; game files stay read-only.'
              : 'You can add a server-visible folder path and scan this library later.'}
          </span>
        </div>
      </form>
      {pendingImage ? (
        <LibraryImageCropper
          file={pendingImage}
          onCancel={() => setPendingImage(null)}
          onSave={(cropped) => {
            setImage(cropped)
            setPendingImage(null)
            if (imageInputRef.current) imageInputRef.current.value = ''
          }}
        />
      ) : null}
      {result?.note ? (
        <PageStatus emptyMessage={result.note} className="od-create-library__message" />
      ) : null}
      <ServerFolderBrowser
        open={browseOpen}
        onClose={() => setBrowseOpen(false)}
        onSelect={({ absolutePath }) => setPath(absolutePath)}
      />
    </section>
  )
}
