import { useEffect, useState } from 'react'
import { fetchGameAssists } from '../api/assists'
import { initiateGameDownload } from '../api/downloads'
import { fetchRemotePlayStatus } from '../api/remotePlay'
import { queueClientCommand } from '../api/clientCommands'
import { honestyApiErrorMessage } from '../utils/playHonesty'
import { isThinSeat } from '../utils/seatMode'
import { showToast } from '../utils/toast'

/**
 * @param {'full' | 'compact'} [variant='full']
 * @param {'not_downloaded' | 'downloaded' | 'installed' | 'update_available'} [lifecycleState]
 * @param {object | null | undefined} [assistPack] when provided, skips fetch; null hides Assists
 */
export function GameActionBar({
  gameUuid,
  gameName = 'game',
  variant = 'full',
  lifecycleState = 'not_downloaded',
  clientConnected = false,
  // Details shows companion presence as a chip on the status row instead, so it
  // can opt out rather than render the same fact twice.
  showPresence = true,
  updateHref,
  className = '',
  onCommandQueued,
  assistPack: assistPackProp,
  remotePlay: remotePlayProp,
  /** Override for tests; defaults to the seat this window was opened as. */
  thinSeat,
}: LooseProps) {
  const isThin = thinSeat === undefined ? isThinSeat() : thinSeat
  const [busyAction, setBusyAction] = useState<any>(null)
  const [statusMessage, setStatusMessage] = useState('')
  const [assistPack, setAssistPack] = useState(assistPackProp === undefined ? null : assistPackProp)
  const [remotePlay, setRemotePlay] = useState(remotePlayProp === undefined ? null : remotePlayProp)
  const updatesUrl = updateHref || `/game_details/${gameUuid}#updates`
  const compact = variant === 'compact'

  useEffect(() => {
    if (assistPackProp !== undefined) {
      setAssistPack(assistPackProp)
      return undefined
    }
    if (!gameUuid) {
      setAssistPack(null)
      return undefined
    }
    const controller = new AbortController()
    fetchGameAssists(gameUuid, { signal: controller.signal })
      .then((data) => {
        if (data?.enabled && data?.pack?.toggles?.length) {
          setAssistPack(data.pack)
        } else {
          setAssistPack(null)
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setAssistPack(null)
        }
      })
    return () => controller.abort()
  }, [gameUuid, assistPackProp])

  useEffect(() => {
    if (remotePlayProp !== undefined) {
      setRemotePlay(remotePlayProp)
      return undefined
    }
    const controller = new AbortController()
    fetchRemotePlayStatus({ signal: controller.signal })
      .then((data) => {
        if (data?.enabled && data?.configured) {
          setRemotePlay(data)
        } else {
          setRemotePlay(null)
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setRemotePlay(null)
        }
      })
    return () => controller.abort()
  }, [remotePlayProp])

  const companionInstallReady = clientConnected && lifecycleState === 'downloaded'
  const companionDownloadReady = clientConnected && lifecycleState === 'not_downloaded'
  const companionUpdateReady = clientConnected && lifecycleState === 'update_available'
  const companionUninstallReady =
    clientConnected && lifecycleState !== 'not_downloaded' && busyAction == null

  const installTitle = !clientConnected
    ? 'Open the Oneirodex companion while browsing to install'
    : lifecycleState === 'installed' || lifecycleState === 'update_available'
      ? 'Already installed on this device'
      : lifecycleState === 'downloaded'
        ? 'Install with Oneirodex companion'
        : 'Queue companion download, then install'
  const updateTitle =
    lifecycleState === 'update_available'
      ? clientConnected
        ? 'Apply update with Oneirodex companion'
        : 'Companion needed to apply — link opens version list'
      : 'No update flagged for this title'
  const uninstallTitle = !clientConnected
    ? 'Open the Oneirodex companion to uninstall locally'
    : lifecycleState === 'not_downloaded'
      ? 'Nothing local to uninstall yet'
      : 'Remove local install only (server library kept)'

  function explain(message: any) {
    setStatusMessage(message)
    showToast(message, 'warn')
  }

  async function sendCommand(action: any) {
    if (!gameUuid || busyAction) {
      return
    }
    setBusyAction(action)
    setStatusMessage('')
    try {
      await queueClientCommand(gameUuid, action)
      const label =
        action === 'download'
          ? 'Download queued for companion'
          : action === 'install'
            ? 'Install queued for companion'
            : action === 'update'
              ? 'Update queued for companion'
              : 'Uninstall queued for companion'
      setStatusMessage(label)
      onCommandQueued?.(action)
      showToast(label, 'success')
    } catch (err: any) {
      const message = err?.message || `Failed to queue ${action}`
      setStatusMessage(message)
      showToast(message, 'error')
    } finally {
      setBusyAction(null)
    }
  }

  function onInstallClick() {
    if (busyAction) return
    if (!clientConnected) {
      explain('Start the Oneirodex companion and keep it signed in, then try again.')
      return
    }
    if (lifecycleState === 'downloaded') {
      void sendCommand('install')
      return
    }
    if (lifecycleState === 'not_downloaded') {
      void sendCommand('download')
      return
    }
    explain('Already installed on this device. Use Update if a newer pack is available.')
  }

  function onUpdateClick(event: any) {
    if (busyAction) {
      event?.preventDefault?.()
      return
    }
    if (companionUpdateReady) {
      event?.preventDefault?.()
      void sendCommand('update')
      return
    }
    if (!clientConnected && lifecycleState === 'update_available') {
      // Allow navigation to version list.
      return
    }
    if (lifecycleState !== 'update_available') {
      event?.preventDefault?.()
      explain('No update is available for this title right now.')
    }
  }

  function onUninstallClick() {
    if (busyAction) return
    if (!clientConnected) {
      explain('Start the Oneirodex companion to uninstall the local copy.')
      return
    }
    if (lifecycleState === 'not_downloaded') {
      explain('Nothing is downloaded or installed on this device yet.')
      return
    }
    void sendCommand('uninstall')
  }

  async function onDownloadClick() {
    if (!gameUuid || busyAction) {
      return
    }
    setBusyAction('download_file')
    setStatusMessage('')
    try {
      await initiateGameDownload(gameUuid)
      setStatusMessage('Download ready — opening Downloads')
      showToast('Download ready — opening Downloads', 'success')
      window.location.assign('/downloads')
    } catch (err: any) {
      const message = honestyApiErrorMessage(err, 'Download failed')
      setStatusMessage(message)
      showToast(message, 'error')
    } finally {
      setBusyAction(null)
    }
  }

  function onRemotePlayClick() {
    const hint =
      remotePlay?.copy_hint ||
      (remotePlay?.moonlight_host
        ? `${remotePlay.moonlight_host}:${remotePlay.moonlight_port || 47989}`
        : '')
    if (!hint) {
      explain('Remote play host is not configured yet.')
      return
    }
    const label = `Copied Moonlight host: ${hint}`
    if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
      void navigator.clipboard.writeText(hint).then(
        () => {
          setStatusMessage(label)
          showToast(label, 'success')
        },
        () => explain('Could not copy — select and copy the host hint manually.'),
      )
      return
    }
    setStatusMessage(`${label} (copy manually)`)
  }

  const installLabel =
    busyAction === 'install' || busyAction === 'download'
      ? 'Queuing…'
      : companionDownloadReady
        ? 'Get with companion'
        : 'Install'

  // TC-3 honesty. A thin seat holds a token with no write:download and ships no
  // install ACL, so Download / Install / Update / Uninstall can never complete
  // here. Say why once instead of offering four buttons that fail — the same
  // pattern as the companion-offline copy.
  if (isThin) {
    return (
      <div
        className={`od-action-bar${compact ? ' od-action-bar--compact' : ''} ${className}`.trim()}
        role="group"
        aria-label={`Actions for ${gameName}`}
        data-lifecycle={lifecycleState}
        data-seat="thin"
      >
        <span className="od-action-bar__status" role="status">
          Browse &amp; social seat — download, install and update happen on the desktop companion.
        </span>
        {remotePlay ? (
          <button
            type="button"
            className="od-action-bar__btn"
            data-action="remote-play"
            title={
              remotePlay.copy_hint
                ? `Copy for Moonlight: ${remotePlay.copy_hint}`
                : 'Copy Moonlight host — open Moonlight app to stream'
            }
            onClick={onRemotePlayClick}
          >
            Play via Moonlight
          </button>
        ) : null}
      </div>
    )
  }

  return (
    <div
      className={`od-action-bar${compact ? ' od-action-bar--compact' : ''} ${className}`.trim()}
      role="group"
      aria-label={`Actions for ${gameName}`}
      data-lifecycle={lifecycleState}
      data-client={clientConnected ? 'connected' : 'absent'}
    >
      {!compact && showPresence ? (
        <span
          className={`od-action-bar__presence${clientConnected ? ' is-online' : ''}`}
          title={
            clientConnected
              ? 'Companion client is online'
              : 'Companion client offline — install/update/uninstall need it'
          }
        >
          {clientConnected ? 'Companion online' : 'Companion offline'}
        </span>
      ) : null}
      <button
        type="button"
        className="od-action-bar__btn od-action-bar__btn--primary"
        data-action="download"
        disabled={busyAction === 'download_file'}
        onClick={() => {
          void onDownloadClick()
        }}
      >
        {busyAction === 'download_file' ? 'Queuing…' : 'Download'}
      </button>
      <button
        type="button"
        className="od-action-bar__btn"
        title={installTitle}
        aria-disabled={!companionInstallReady && !companionDownloadReady}
        data-action="install"
        onClick={onInstallClick}
      >
        {installLabel}
      </button>
      {companionUpdateReady ? (
        <button
          type="button"
          className="od-action-bar__btn"
          title={updateTitle}
          data-action="update"
          onClick={() => {
            void sendCommand('update')
          }}
        >
          {busyAction === 'update' ? 'Queuing…' : 'Update'}
        </button>
      ) : (
        <a
          className={`od-action-bar__btn${lifecycleState !== 'update_available' ? ' is-disabled' : ''}`}
          href={updatesUrl}
          title={updateTitle}
          aria-disabled={lifecycleState !== 'update_available'}
          data-action="update"
          onClick={onUpdateClick}
        >
          Update
        </a>
      )}
      <button
        type="button"
        className="od-action-bar__btn od-action-bar__btn--danger"
        title={uninstallTitle}
        aria-disabled={!companionUninstallReady}
        data-action="uninstall"
        onClick={onUninstallClick}
      >
        {busyAction === 'uninstall' ? 'Queuing…' : 'Uninstall'}
      </button>
      {assistPack ? (
        <button
          type="button"
          className="od-action-bar__btn"
          data-action="assists"
          title={
            clientConnected
              ? 'Open single-player assists in the companion'
              : 'Assists require the Oneirodex companion (single-player / offline only)'
          }
          onClick={() => {
            const label = clientConnected
              ? 'Assists available in companion overlay'
              : 'Open companion to use Assists (single-player only)'
            setStatusMessage(label)
            showToast(label, clientConnected ? 'success' : 'warn')
          }}
        >
          Assists
        </button>
      ) : null}
      {remotePlay ? (
        <button
          type="button"
          className="od-action-bar__btn"
          data-action="remote-play"
          title={
            remotePlay.copy_hint
              ? `Copy for Moonlight: ${remotePlay.copy_hint}`
              : 'Copy Moonlight host — open Moonlight app to stream'
          }
          onClick={onRemotePlayClick}
        >
          Play via Moonlight
        </button>
      ) : null}
      {statusMessage ? (
        <span className="od-action-bar__status" role="status">
          {statusMessage}
        </span>
      ) : null}
    </div>
  )
}
