// Toasts on every mutation (GT-B25). Outcomes were reported inline only,
// which is easy to miss when the triggering control has scrolled away.
import { useCallback, useEffect, useRef, useState } from 'react'
import { csrfHeaders, csrfToken, postJson } from '../api/adminApi'
import { errorText } from '../utils/errorText'
import { Button, PageStatus } from '@oneirodex/ui'
import { MetricStrip } from './opsWidgets'
import { showToast } from '../utils/toast'
import {
  ENDPOINT,
  coreLabel,
  formatBytes,
  readError,
  versionChoice,
} from './firmware/firmwareModel'
import type { FirmwareCoreStatus, FirmwareFile, FirmwarePlan } from './firmware/firmwareModel'
import { FirmwareMissingDialog } from './firmware/FirmwareMissingDialog'
export { coreLabel, formatBytes, readError } from './firmware/firmwareModel'
import './OpenPathModal.css'

export function EmulatorFirmwarePanel() {
  const [files, setFiles] = useState<FirmwareFile[]>([])
  const [cores, setCores] = useState<FirmwareCoreStatus[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [sourceFolder, setSourceFolder] = useState('')
  const [volumeMarkdown, setVolumeMarkdown] = useState('')
  const [plan, setPlan] = useState<FirmwarePlan | null>(null)
  const [selections, setSelections] = useState<Record<string, string>>({})
  const [skipped, setSkipped] = useState<Set<string>>(() => new Set())
  const [overwrite, setOverwrite] = useState(false)
  const [reportOpen, setReportOpen] = useState(false)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const folderInputRef = useRef<HTMLInputElement | null>(null)
  const [uploadProgress, setUploadProgress] = useState({ done: 0, total: 0 })

  const reportMarkdown = plan?.missing_markdown || volumeMarkdown

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await fetch(ENDPOINT, { credentials: 'same-origin' })
      if (!response.ok) {
        throw new Error(await readError(response, 'Could not read the firmware volume.'))
      }
      const data = await response.json()
      setFiles(Array.isArray(data.files) ? data.files : [])
      setCores(Array.isArray(data.cores) ? data.cores : [])
      setVolumeMarkdown(typeof data.missing_markdown === 'string' ? data.missing_markdown : '')
      if (typeof data.import_source === 'string' && data.import_source) {
        setSourceFolder((prev) => prev || data.import_source)
      }
    } catch (err) {
      setError(errorText(err) || 'Could not read the firmware volume.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const applyPlan = useCallback((next: FirmwarePlan) => {
    const picks: Record<string, string> = {}
    const skip = new Set<string>()
    for (const match of next.matches || []) {
      picks[match.name] = match.chosen || ''
      if (match.already) skip.add(match.name)
    }
    setPlan(next)
    setSelections(picks)
    setSkipped(skip)
  }, [])

  const scanCollection = useCallback(async () => {
    setBusy('scan')
    setError(null)
    setNotice(null)
    try {
      const data = await postJson(`${ENDPOINT}/scan`, { source: sourceFolder })
      applyPlan(data)
      setReportOpen(true)
    } catch (err) {
      const text = errorText(err) || 'Could not scan that folder.'
      setError(text)
      showToast(text, 'error')
    } finally {
      setBusy(null)
    }
  }, [applyPlan, sourceFolder])

  const installMatching = useCallback(async () => {
    setBusy('install')
    setError(null)
    setNotice(null)
    try {
      const data = await postJson(`${ENDPOINT}/install`, {
        source: sourceFolder,
        selections,
        skipped: [...skipped],
        overwrite,
      })
      applyPlan(data)
      const copied = Number(data.copied_count) || 0
      const summary = copied
        ? `Installed ${copied} firmware file${copied === 1 ? '' : 's'} from the collection.`
        : 'Nothing new to install — already on the volume or skipped.'
      setNotice(summary)
      showToast(summary, 'success')
      setReportOpen(true)
      await load()
    } catch (err) {
      const text = errorText(err) || 'Could not install firmware from that folder.'
      setError(text)
      showToast(text, 'error')
    } finally {
      setBusy(null)
    }
  }, [applyPlan, load, overwrite, selections, skipped, sourceFolder])

  const upload = useCallback(
    async (file: File | null | undefined) => {
      if (!file) return
      setBusy('upload')
      setError(null)
      setNotice(null)
      try {
        const form = new FormData()
        form.append('file', file)
        // CSRFProtect is app-wide, so an upload without a token is rejected
        // with 400 before the route ever sees the file — which is what made
        // firmware upload look broken. Sent both ways, as the other FormData
        // upload in this app does: the header for CSRFProtect, and the field
        // for any surface that reads it out of the form.
        form.append('csrf_token', csrfToken())
        const response = await fetch(ENDPOINT, {
          method: 'POST',
          body: form,
          credentials: 'same-origin',
          headers: csrfHeaders(),
        })
        if (!response.ok) {
          throw new Error(await readError(response, 'Upload failed.'))
        }
        setNotice(`${file.name} added to the firmware volume.`)
        showToast(`${file.name} added to the firmware volume.`, 'success')
        if (inputRef.current) inputRef.current.value = ''
        await load()
      } catch (err) {
        const text = errorText(err) || 'Upload failed.'
        setError(text)
        showToast(text, 'error')
      } finally {
        setBusy(null)
      }
    },
    [load],
  )

  const uploadFolder = useCallback(
    async (selected: FileList | null) => {
      if (!selected?.length) return
      setBusy('folder-upload')
      setError(null)
      setNotice(null)
      setUploadProgress({ done: 0, total: 0 })
      try {
        const requiredNames = new Map<string, string>()
        for (const core of cores) {
          for (const name of core.required || []) requiredNames.set(name.toLowerCase(), name)
        }

        const grouped = new Map<string, File[]>()
        let ignored = 0
        for (const file of Array.from(selected)) {
          const canonical = requiredNames.get(file.name.toLowerCase())
          if (!canonical) {
            ignored += 1
            continue
          }
          grouped.set(canonical, [...(grouped.get(canonical) || []), file])
        }

        const conflicts = [...grouped.entries()].filter(([, copies]) => copies.length > 1)
        if (conflicts.length) {
          throw new Error(
            `${conflicts.length} required filename${conflicts.length === 1 ? ' appears' : 's appear'} more than once. Use the collection scanner to review regional copies before installing.`,
          )
        }

        const existing = new Set(files.map((file) => file.name.toLowerCase()))
        const candidates = [...grouped.entries()].filter(
          ([name]) => overwrite || !existing.has(name.toLowerCase()),
        )
        const alreadyPresent = grouped.size - candidates.length
        setUploadProgress({ done: 0, total: candidates.length })
        if (!candidates.length) {
          const summary = `No new matching files to upload. ${alreadyPresent} already on the volume; ${ignored} not required by configured cores.`
          setNotice(summary)
          showToast(summary, 'success')
          return
        }

        let uploaded = 0
        let failed = 0
        for (const [canonical, copies] of candidates) {
          const form = new FormData()
          form.append('file', copies[0], canonical)
          form.append('csrf_token', csrfToken())
          try {
            const response = await fetch(ENDPOINT, {
              method: 'POST',
              body: form,
              credentials: 'same-origin',
              headers: csrfHeaders(),
            })
            if (!response.ok) {
              throw new Error(await readError(response, 'Upload failed.'))
            }
            uploaded += 1
          } catch {
            failed += 1
          }
          setUploadProgress((progress) => ({ ...progress, done: progress.done + 1 }))
        }

        const summary = `Uploaded ${uploaded} matching file${uploaded === 1 ? '' : 's'}; ${alreadyPresent} already on the volume; ${ignored} not required by configured cores.`
        setNotice(summary)
        let failureNotice: string | null = null
        if (failed) {
          failureNotice = `${summary} ${failed} file${failed === 1 ? '' : 's'} could not be uploaded; check the file limits and try again.`
          showToast(failureNotice, 'error')
        } else {
          showToast(summary, 'success')
        }
        await load()
        if (failureNotice) setError(failureNotice)
      } catch (err) {
        const text = errorText(err) || 'Could not upload that firmware folder.'
        setError(text)
        showToast(text, 'error')
      } finally {
        if (folderInputRef.current) folderInputRef.current.value = ''
        setBusy(null)
      }
    },
    [cores, files, load, overwrite],
  )

  const ready = cores.filter((c) => c.ready).length
  const missing = cores.length - ready
  const working = Boolean(busy)
  const busyLabel =
    busy === 'scan'
      ? 'Scanning…'
      : busy === 'install'
        ? 'Installing…'
        : busy === 'upload'
          ? 'Uploading…'
          : busy === 'folder-upload'
            ? `Uploading ${uploadProgress.done} of ${uploadProgress.total}…`
            : null

  return (
    <section className="od-admin-panel" aria-labelledby="od-firmware-heading">
      <h2 id="od-firmware-heading" className="od-section-head__title">
        Firmware / BIOS
      </h2>
      <p className="od-admin-lede">
        Some cores need system files you legally own. Upload one file, scan a folder of dumps you
        already have, or mount them at <code>EMULATOR_BIOS_PATH</code>. Oneirodex never downloads
        BIOS for you.
      </p>

      {!loading && cores.length > 0 ? (
        <MetricStrip
          label="Firmware coverage"
          items={[
            {
              id: 'ready',
              label: 'Cores ready',
              value: ready,
              hint: `of ${cores.length}`,
              tone: ready === cores.length ? 'good' : 'info',
            },
            {
              id: 'missing',
              label: 'Cores missing files',
              value: missing,
              hint: missing > 0 ? 'play falls back' : 'all covered',
              tone: missing > 0 ? 'warning' : 'good',
            },
            {
              id: 'files',
              label: 'Files on volume',
              value: files.length,
              hint: 'uploaded',
              tone: 'info',
            },
          ]}
        />
      ) : null}

      <h3 className="od-section-head__title">Install from a collection</h3>
      <p className="od-admin-lede">
        Point at a folder on this server. Subfolders are searched too. Matching names are offered
        for every system the service supports; if two dumps share a filename, pick which one that
        system should use. Cores read one file per name from the firmware root, so a shared filename
        is one dump for every system that uses it.
      </p>
      <label className="od-admin-lede" htmlFor="od-firmware-source">
        Firmware collection folder
      </label>
      <input
        id="od-firmware-source"
        className="od-input"
        type="text"
        value={sourceFolder}
        disabled={working}
        placeholder="Folder on this server (searched recursively)"
        onChange={(event) => setSourceFolder(event.target.value)}
      />
      <div className="od-btn-bar">
        <Button
          type="button"
          variant="primary"
          disabled={working || !sourceFolder.trim()}
          onClick={() => void scanCollection()}
        >
          Scan collection
        </Button>
        <Button
          type="button"
          disabled={working || !sourceFolder.trim()}
          onClick={() => void installMatching()}
        >
          Install matching firmware
        </Button>
        <Button
          type="button"
          disabled={working || !reportMarkdown}
          onClick={() => setReportOpen(true)}
        >
          Show missing report
        </Button>
        <label>
          <input
            type="checkbox"
            checked={overwrite}
            disabled={working}
            onChange={(event) => setOverwrite(event.target.checked)}
          />{' '}
          Replace files already on the volume
        </label>
      </div>

      <div className="od-btn-bar">
        <input
          ref={inputRef}
          className="od-input"
          type="file"
          aria-label="Firmware file"
          disabled={working}
          onChange={(event) => upload(event.target.files?.[0])}
        />
        {busyLabel ? (
          <span role="status" aria-busy="true">
            {busyLabel}
          </span>
        ) : null}
      </div>

      <div className="od-btn-bar">
        <label className="od-admin-lede" htmlFor="od-firmware-folder">
          Upload matching firmware from a folder on this device
        </label>
        <input
          ref={folderInputRef}
          id="od-firmware-folder"
          className="od-input"
          type="file"
          aria-label="Firmware folder"
          multiple
          disabled={working}
          {...({ webkitdirectory: 'true' } as Record<string, string>)}
          onChange={(event) => void uploadFolder(event.currentTarget.files)}
        />
        <p className="od-error__detail">
          Only filenames required by configured cores are uploaded. If the folder contains multiple
          versions of a required filename, use the collection scanner to choose one.
        </p>
      </div>

      {/* `Uploading…` / `Scanning…` / `Installing…` and `notice` stay
          hand-rolled on purpose: the first is inline feedback on one control,
          the second is a success message, and PageStatus models neither. */}
      <PageStatus error={error} onRetry={load} />

      {notice ? (
        <p className="od-adminpage-status" role="status">
          {notice}
        </p>
      ) : null}

      <PageStatus loading={loading} inline loadingMessage="Reading firmware volume…" />

      {!loading && !error && plan ? (
        <>
          <h3 className="od-section-head__title">Matching dumps in the collection</h3>
          {(plan.matches || []).length === 0 ? (
            <p className="od-empty">
              No filenames this service asks for were in that folder. The missing report lists what
              to add.
            </p>
          ) : (
            <ul className="od-list">
              {(plan.matches || []).map((match) => {
                const systems = (match.systems || []).map((row) => row.label).join(', ')
                const included = !skipped.has(match.name)
                const versions = match.versions || []
                const conflict = versions.filter((row) => row.digest).length > 1
                return (
                  <li key={match.name} className="od-list__row">
                    <label>
                      <input
                        type="checkbox"
                        checked={included}
                        disabled={working}
                        onChange={(event) => {
                          setSkipped((prev) => {
                            const next = new Set(prev)
                            if (event.target.checked) next.delete(match.name)
                            else next.add(match.name)
                            return next
                          })
                        }}
                      />{' '}
                      Install <code>{match.name}</code>
                      {match.already ? ' (already on the volume)' : ''}
                    </label>
                    {systems ? <p className="od-error__detail">Systems: {systems}</p> : null}
                    {match.note ? <p className="od-error__detail">{match.note}</p> : null}
                    {conflict ? (
                      <fieldset>
                        <legend>Which dump for {match.name}</legend>
                        {versions.map((version) => {
                          const choice = versionChoice(version)
                          const id = `od-fw-${match.name}-${choice}`
                          return (
                            <label key={choice} htmlFor={id}>
                              <input
                                id={id}
                                type="radio"
                                name={`od-fw-${match.name}`}
                                value={choice}
                                checked={selections[match.name] === choice}
                                disabled={working || !included}
                                onChange={() => {
                                  setSelections((prev) => ({ ...prev, [match.name]: choice }))
                                }}
                              />{' '}
                              {formatBytes(version.size)} ·{' '}
                              {version.digest ? version.digest.slice(0, 12) : 'single copy'}
                              {(version.count ?? 0) > 1 ? ` · ${version.count} copies` : ''}
                              {version.paths?.length
                                ? ` · ${(version.paths || []).join(', ')}`
                                : ''}
                            </label>
                          )
                        })}
                      </fieldset>
                    ) : null}
                  </li>
                )
              })}
            </ul>
          )}
        </>
      ) : null}

      {!loading && !error ? (
        <>
          <h3 className="od-section-head__title">Cores</h3>
          {cores.length === 0 ? (
            <p className="od-empty">No cores declare firmware requirements.</p>
          ) : (
            <details className="od-fold">
              <summary className="od-fold__summary">
                Core requirements · {ready} ready · {missing} need files
              </summary>
              <ul className="od-list">
                {cores.map((core) => (
                  <li key={core.core} className="od-list__row">
                    <strong>{coreLabel(core.core)}</strong>{' '}
                    <span>
                      {core.ready
                        ? 'ready'
                        : core.misplaced?.length
                          ? 'files found, but in a subfolder'
                          : 'missing system files'}
                    </span>
                    <p className="od-error__detail">
                      Accepts: {(core.required || []).join(', ')}
                      {core.present?.length ? ` · present: ${core.present.join(', ')}` : ''}
                    </p>
                    {core.misplaced?.length ? (
                      <p className="od-error__detail">
                        Move to the firmware root to load:{' '}
                        {core.misplaced.map((f) => `${f.subdir}/${f.name}`).join(', ')}
                      </p>
                    ) : null}
                  </li>
                ))}
              </ul>
            </details>
          )}

          <h3 className="od-section-head__title">Files on volume</h3>
          {files.length === 0 ? (
            <p className="od-empty">
              No firmware found on the volume. Cores that need it will stay unavailable for browser
              play. Files in subfolders are listed here too — if you copied a set in and see
              nothing, check the path the volume is actually mounted at.
            </p>
          ) : (
            <details className="od-fold">
              <summary className="od-fold__summary">Firmware files · {files.length} uploaded</summary>
              <ul className="od-list">
                {files.map((file) => (
                  <li key={`${file.subdir}/${file.name}`} className="od-list__row">
                    <code>{file.subdir ? `${file.subdir}/${file.name}` : file.name}</code>{' '}
                    <span>{formatBytes(file.size)}</span>
                    {file.loadable === false ? (
                      <span className="od-badge od-badge--warn">subfolder</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      ) : null}

      <FirmwareMissingDialog
        open={reportOpen}
        markdown={reportMarkdown}
        onClose={() => setReportOpen(false)}
      />
    </section>
  )
}
