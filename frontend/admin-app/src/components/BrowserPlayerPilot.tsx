import { useCallback, useEffect, useId, useState, type ChangeEvent } from 'react'
import { getJson, putJson } from '../api/adminApi'
import { errorText } from '../utils/errorText'
import { PageStatus } from '@oneirodex/ui'
import { showToast } from '../utils/toast'

const ENDPOINT = '/api/browser-player-settings'

type EngineId = 'webretro' | 'emulatorjs'

const ENGINE_LABELS: Record<EngineId, string> = {
  webretro: 'WebRetro',
  emulatorjs: 'EmulatorJS',
}

/**
 * Browser play engine — admin default + the BP-1 NES pilot flag. Lives on the
 * Emulators page next to firmware because that is where operators already
 * decide how browser play boots.
 *
 * Engine B (EmulatorJS, BP-2) appears in the choice only when the server
 * reports it installed (`browser_players_available`); otherwise the option is
 * shown disabled with the reason, so an operator learns *how* to get it rather
 * than wondering why it is missing.
 */
export function BrowserPlayerPilot() {
  const checkboxId = useId()
  const memberChoiceId = useId()
  const radioName = useId()
  const [pilot, setPilot] = useState(false)
  const [memberChoice, setMemberChoice] = useState(false)
  const [engine, setEngine] = useState<EngineId>('webretro')
  const [available, setAvailable] = useState<EngineId[]>(['webretro'])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const apply = useCallback((data: Record<string, unknown>) => {
    setPilot(Boolean(data.nostalgist_nes_pilot))
    setMemberChoice(Boolean(data.browser_player_allow_member_choice))
    const next = data.browser_player_default
    if (next === 'webretro' || next === 'emulatorjs') setEngine(next)
    const list = Array.isArray(data.browser_players_available)
      ? (data.browser_players_available.filter(
          (e): e is EngineId => e === 'webretro' || e === 'emulatorjs',
        ) as EngineId[])
      : ['webretro' as EngineId]
    setAvailable(list.length ? list : ['webretro'])
  }, [])

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    return getJson(ENDPOINT)
      .then(apply)
      .catch((err) => {
        setError(err)
      })
      .finally(() => {
        setLoading(false)
      })
  }, [apply])

  useEffect(() => {
    void load()
  }, [load])

  const onToggle = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const next = event.target.checked
    setBusy(true)
    setError(null)
    try {
      const saved = await putJson(ENDPOINT, { nostalgist_nes_pilot: next })
      setPilot(Boolean(saved.nostalgist_nes_pilot))
      showToast(
        next
          ? 'NES Play will use the Nostalgist host (no save bar yet).'
          : 'NES Play uses the WebRetro room.',
        'success',
      )
    } catch (err) {
      setError(err)
      showToast(errorText(err) || 'Could not save browser player settings.', 'error')
    } finally {
      setBusy(false)
    }
  }, [])

  const onMemberChoice = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const next = event.target.checked
    setBusy(true)
    setError(null)
    try {
      const saved = await putJson(ENDPOINT, { browser_player_allow_member_choice: next })
      setMemberChoice(Boolean(saved.browser_player_allow_member_choice))
      showToast(
        next
          ? 'Members can pick their engine under Preferences → Play in browser.'
          : 'Members play with the default engine.',
        'success',
      )
    } catch (err) {
      setError(err)
      showToast(errorText(err) || 'Could not save browser player settings.', 'error')
    } finally {
      setBusy(false)
    }
  }, [])

  const onEngine = useCallback(
    async (event: ChangeEvent<HTMLInputElement>) => {
      const next = event.target.value as EngineId
      if (next === engine) return
      setBusy(true)
      setError(null)
      try {
        const saved = await putJson(ENDPOINT, { browser_player_default: next })
        apply(saved)
        showToast(`Browser play uses ${ENGINE_LABELS[next]} for supported systems.`, 'success')
      } catch (err) {
        setError(err)
        showToast(errorText(err) || 'Could not save browser player settings.', 'error')
      } finally {
        setBusy(false)
      }
    },
    [apply, engine],
  )

  const emulatorjsInstalled = available.includes('emulatorjs')

  return (
    <section className="od-admin-panel" aria-labelledby="od-browser-player-heading">
      <h2 id="od-browser-player-heading" className="od-section-head__title">
        Browser play engine
      </h2>
      <p className="od-admin-lede">
        WebRetro ships with the image. EmulatorJS is a second shell with its own UI and cores; it is
        offered once an EmulatorJS release is in the server&rsquo;s data bind (
        <code>scripts/fetch-emulatorjs.sh</code>). Either way ROMs and cores stay on this box, and a
        system the chosen engine cannot run falls back to WebRetro.
      </p>
      <PageStatus
        loading={loading}
        loadingMessage="Reading browser player settings…"
        error={error}
        onRetry={load}
        errorMessage="Could not read browser player settings."
        inline
      />
      {loading || error ? null : (
        <>
          <fieldset className="od-fieldset" disabled={busy}>
            <legend>Default engine</legend>
            {(['webretro', 'emulatorjs'] as EngineId[]).map((id) => {
              const installed = available.includes(id)
              return (
                <label key={id} className="od-radio" data-engine={id}>
                  <input
                    type="radio"
                    name={radioName}
                    value={id}
                    checked={engine === id}
                    disabled={!installed}
                    onChange={onEngine}
                  />{' '}
                  {ENGINE_LABELS[id]}
                  {id === 'emulatorjs' && !installed ? (
                    <span className="od-muted"> — not installed on this server</span>
                  ) : null}
                </label>
              )
            })}
          </fieldset>
          {emulatorjsInstalled ? null : (
            <p className="od-muted">
              To offer EmulatorJS: run <code>scripts/fetch-emulatorjs.sh</code> into the directory
              Compose binds as <code>EMULATORJS_HOST_PATH</code>, then reload this page.
            </p>
          )}
          {/* Stored regardless; only has an effect once two engines are
              installed, and the member modal only shows the picker then. */}
          <label htmlFor={memberChoiceId}>
            <input
              id={memberChoiceId}
              type="checkbox"
              checked={memberChoice}
              disabled={busy}
              onChange={onMemberChoice}
            />{' '}
            Let members choose their engine
            {emulatorjsInstalled ? null : (
              <span className="od-muted"> — takes effect once a second engine is installed</span>
            )}
          </label>
          <label htmlFor={checkboxId}>
            <input
              id={checkboxId}
              type="checkbox"
              checked={pilot}
              disabled={busy}
              onChange={onToggle}
            />{' '}
            NES Nostalgist pilot
          </label>
        </>
      )}
    </section>
  )
}
