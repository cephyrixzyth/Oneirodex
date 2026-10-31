import { useCallback, useEffect, useMemo, useState, type DragEvent } from 'react'

import { useParams } from 'react-router-dom'
import { Button, PageStatus, confirmAction } from '@oneirodex/ui'
import { deleteJson, getJson, postForm, postJson } from '../api/adminApi'
import { ArtworkPicker } from '../components/ArtworkPicker'
import { Page } from '../components/Page'
import { errorText } from '../utils/errorText'
import './EditGameImagesPage.css'
import { AdminLink } from '../components/AdminLink'

type GameImage = { id: number; image_type: string; url: string | null; is_downloaded: boolean }

const KINDS = ['cover', 'screenshot', 'box', 'cart', 'disc', 'logo', 'hero', 'fanart']

export function EditGameImagesPage() {
  const { gameUuid = '' } = useParams()
  const [gameName, setGameName] = useState('')
  const [images, setImages] = useState<GameImage[] | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')
  const [scanRunning, setScanRunning] = useState(false)
  const [uploadKind, setUploadKind] = useState('screenshot')
  const [refreshStatus, setRefreshStatus] = useState('')
  const [screenshotDragActive, setScreenshotDragActive] = useState(false)

  const load = useCallback(async () => {
    setError('')
    setImages(null)
    try {
      const [state, imageData] = await Promise.all([
        getJson(`/api/admin/manual-identify/${encodeURIComponent(gameUuid)}`),
        getJson(`/api/game_images/${encodeURIComponent(gameUuid)}`),
      ])
      setGameName(String(state.game?.name || 'Game'))
      setScanRunning(Boolean(state.scan_running))
      setImages(Array.isArray(imageData.images) ? imageData.images : [])
    } catch (cause) {
      setError(errorText(cause) || 'Unable to load this game’s artwork.')
    }
  }, [gameUuid])

  useEffect(() => {
    void load()
  }, [load])

  const byKind = useMemo(
    () =>
      Object.fromEntries(
        KINDS.map((kind) => [kind, images?.filter((image) => image.image_type === kind) || []]),
      ),
    [images],
  )

  async function upload(file: File, kind: string) {
    setBusy(`upload-${kind}`)
    setError('')
    try {
      const form = new FormData()
      form.append('file', file)
      form.append('image_type', kind)
      await postForm(`/upload_image/${encodeURIComponent(gameUuid)}`, form)
      await load()
    } catch (cause) {
      setError(errorText(cause) || `Unable to upload ${kind} artwork.`)
    } finally {
      setBusy('')
    }
  }

  async function uploadScreenshots(files: File[]) {
    for (const file of files) await upload(file, 'screenshot')
  }

  function handleScreenshotDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setScreenshotDragActive(false)
    if (scanRunning || busy) return
    void uploadScreenshots(Array.from(event.dataTransfer.files))
  }

  async function deleteImage(image: GameImage) {
    if (
      image.image_type === 'cover' &&
      !(await confirmAction({
        title: 'Delete cover image?',
        body: 'Are you sure you want to delete the cover image?',
        confirmLabel: 'Delete cover image',
        tone: 'danger',
      }))
    )
      return
    setBusy(`delete-${image.id}`)
    setError('')
    try {
      await postJson('/delete_image', {
        image_id: image.id,
        is_cover: image.image_type === 'cover',
      })
      await load()
    } catch (cause) {
      setError(errorText(cause) || 'Unable to delete this image.')
    } finally {
      setBusy('')
    }
  }

  async function refreshFromProvider() {
    if (
      !(await confirmAction({
        title: 'Refresh artwork from IGDB?',
        body: 'Oneirodex will contact the configured IGDB service and replace eligible images for this game.',
        confirmLabel: 'Start artwork refresh',
        tone: 'neutral',
      }))
    )
      return
    setBusy('refresh')
    setError('')
    setRefreshStatus('Starting artwork refresh…')
    try {
      const result = await postJson(`/refresh_game_images/${encodeURIComponent(gameUuid)}`, {})
      setRefreshStatus(
        result.message || 'Artwork refresh started. Check back shortly for new images.',
      )
      await load()
    } catch (cause) {
      setError(errorText(cause) || 'Unable to start artwork refresh.')
    } finally {
      setBusy('')
    }
  }

  const title = gameName || 'Edit game images'
  return (
    <Page
      title={
        <>
          <span className="od-edit-game-images__eyebrow">Library · Artwork</span>
          <span className="od-edit-game-images__title">Edit Images</span>
        </>
      }
      documentTitle="Edit Images"
      lede={
        <>
          <strong>{title}</strong>
          <br />
          Cover, screenshots, and artwork search. Changes apply to the library item immediately.
        </>
      }
      actions={
        <div className="od-edit-game-images__actions" aria-label="Image editor navigation">
          <a className="od-cbtn" href={`/game/${encodeURIComponent(gameUuid)}`}>
            Back to details
          </a>
          <AdminLink className="od-cbtn" to={`/game_edit/${encodeURIComponent(gameUuid)}`}>
            Edit details
          </AdminLink>
          <AdminLink
            className="od-cbtn"
            to={`/admin/images?game=${encodeURIComponent(gameUuid)}&name=${encodeURIComponent(title)}`}
          >
            Art &amp; images
          </AdminLink>
        </div>
      }
      className="od-edit-game-images"
    >
      {scanRunning ? (
        <PageStatus announcement="status" className="od-admin-lede">
          A scan is running. Artwork changes are paused until it finishes.
        </PageStatus>
      ) : null}
      {refreshStatus ? (
        <PageStatus announcement="status" className="od-admin-lede">
          {refreshStatus}
        </PageStatus>
      ) : null}
      {error ? (
        <PageStatus error={error} onRetry={() => void load()} retryLabel="Retry loading artwork" />
      ) : null}
      {images ? (
        <>
          <section
            className="od-admin-panel od-edit-game-images__panel"
            aria-labelledby="od-game-cover-title"
          >
            <h2 id="od-game-cover-title" className="od-admin-panel-title">
              Cover Image
            </h2>
            <div className="od-edit-game-images__cover-layout">
              <div className="od-edit-game-images__cover">
                {byKind.cover?.[0]?.url ? (
                  <img src={byKind.cover[0].url} alt={`${title} cover`} />
                ) : (
                  <div className="od-edit-game-images__empty">
                    {title}
                    <span>No cover art</span>
                  </div>
                )}
              </div>
              <div className="od-edit-game-images__cover-controls">
                <label className="od-admin-field">
                  Upload cover
                  <input
                    className="od-admin-input"
                    type="file"
                    accept="image/jpeg,image/png,image/gif"
                    disabled={Boolean(busy) || scanRunning}
                    onChange={(event) => {
                      const file = event.currentTarget.files?.[0]
                      if (file) void upload(file, 'cover')
                      event.currentTarget.value = ''
                    }}
                  />
                </label>
                {byKind.cover?.map((image) => (
                  <Button
                    key={image.id}
                    className="od-btn--danger"
                    onClick={() => void deleteImage(image)}
                    disabled={Boolean(busy) || scanRunning}
                  >
                    Delete cover image
                  </Button>
                ))}
              </div>
            </div>
          </section>
          <section
            className="od-admin-panel od-edit-game-images__panel"
            aria-labelledby="od-artwork-search-title"
          >
            <div className="od-edit-game-images__section-heading">
              <h2 id="od-artwork-search-title" className="od-admin-panel-title">
                Artwork Search
              </h2>
              <Button
                className="od-btn--secondary"
                onClick={() => void refreshFromProvider()}
                disabled={Boolean(busy) || scanRunning || images === null}
              >
                Refresh from IGDB
              </Button>
            </div>
            {scanRunning ? null : (
              <ArtworkPicker
                gameUuid={gameUuid}
                gameName={title}
                onApplied={() => void load()}
                compact
              />
            )}
          </section>
          <section
            className="od-admin-panel od-edit-game-images__panel"
            aria-labelledby="od-game-screenshots-title"
          >
            <h2 id="od-game-screenshots-title" className="od-admin-panel-title">
              Screenshots
            </h2>
            {byKind.screenshot?.length ? (
              <div className="od-edit-game-images__grid">
                {byKind.screenshot.map((image) => (
                  <figure key={image.id}>
                    <img src={image.url || ''} alt={`${title} screenshot`} />
                    <figcaption>
                      <Button
                        className="od-btn--danger"
                        onClick={() => void deleteImage(image)}
                        disabled={Boolean(busy) || scanRunning}
                      >
                        Delete screenshot
                      </Button>
                    </figcaption>
                  </figure>
                ))}
              </div>
            ) : (
              <p className="od-admin-lede">No screenshots uploaded.</p>
            )}
            <label className="od-admin-field">
              Upload screenshots
              <div
                className={`od-edit-game-images__dropzone${screenshotDragActive ? ' is-active' : ''}`}
                role="group"
                aria-label="Screenshot upload area"
                onDragEnter={(event) => {
                  event.preventDefault()
                  setScreenshotDragActive(true)
                }}
                onDragOver={(event) => event.preventDefault()}
                onDragLeave={(event) => {
                  const target = event.relatedTarget
                  if (!(target instanceof Node) || !event.currentTarget.contains(target))
                    setScreenshotDragActive(false)
                }}
                onDrop={handleScreenshotDrop}
              >
                <span aria-live="polite">
                  {screenshotDragActive
                    ? 'Drop images to upload.'
                    : 'Drag and drop images here, or choose files below.'}
                </span>
                <input
                  className="od-admin-input"
                  type="file"
                  accept="image/jpeg,image/png,image/gif"
                  multiple
                  aria-label="Upload screenshots"
                  disabled={Boolean(busy) || scanRunning}
                  onChange={(event) => {
                    const files = Array.from(event.currentTarget.files || [])
                    event.currentTarget.value = ''
                    void uploadScreenshots(files)
                  }}
                />
              </div>
            </label>
          </section>
          <section
            className="od-admin-panel od-edit-game-images__panel"
            aria-labelledby="od-game-other-images-title"
          >
            <h2 id="od-game-other-images-title" className="od-admin-panel-title">
              Other artwork
            </h2>
            <p className="od-admin-lede">
              Box, cart, disc, logo, hero, and fan art. Singular kinds replace the previous primary
              image.
            </p>
            <label className="od-admin-field">
              Artwork kind
              <select
                className="od-admin-input"
                value={uploadKind}
                onChange={(event) => setUploadKind(event.target.value)}
                disabled={Boolean(busy) || scanRunning}
              >
                {KINDS.filter((kind) => kind !== 'cover' && kind !== 'screenshot').map((kind) => (
                  <option key={kind} value={kind}>
                    {kind[0].toUpperCase() + kind.slice(1)}
                  </option>
                ))}
              </select>
            </label>
            <label className="od-admin-field">
              Upload artwork
              <input
                className="od-admin-input"
                type="file"
                accept="image/jpeg,image/png,image/gif"
                disabled={Boolean(busy) || scanRunning}
                onChange={(event) => {
                  const file = event.currentTarget.files?.[0]
                  if (file) void upload(file, uploadKind)
                  event.currentTarget.value = ''
                }}
              />
            </label>
            {KINDS.filter((kind) => kind !== 'cover' && kind !== 'screenshot').map((kind) =>
              byKind[kind]?.length ? (
                <div key={kind} className="od-edit-game-images__kind">
                  <h3>{kind[0].toUpperCase() + kind.slice(1)}</h3>
                  <div className="od-edit-game-images__grid">
                    {byKind[kind].map((image) => (
                      <figure key={image.id}>
                        <img src={image.url || ''} alt={`${title} ${kind}`} />
                        <figcaption>
                          <Button
                            className="od-btn--danger"
                            onClick={() => void deleteImage(image)}
                            disabled={Boolean(busy) || scanRunning}
                          >
                            Delete {kind}
                          </Button>
                        </figcaption>
                      </figure>
                    ))}
                  </div>
                </div>
              ) : null,
            )}
          </section>
        </>
      ) : (
        <PageStatus loading={!error} loadingMessage="Loading game artwork…" />
      )}
    </Page>
  )
}
