import type { MoonfallInput, MoonfallSettings } from './model'
import type { MoonfallSession } from './session'
import { MISSION_NAMES, MISSION_ROUTES, MISSION_REQUIREMENTS } from './table'
import type { RoomGameMenu } from '../roomScene'

type View = ReturnType<MoonfallSession['view']>
export function moonfallMenu(view: View): RoomGameMenu {
  const actions: RoomGameMenu['actions'] = []
  const add = (label: string, command: string) =>
    actions.push({ label, action: '@moonfall-' + command, disabled: view.busy })
  if (view.status !== 'denied' && view.menuPage !== 'main') {
    const settings = view.state.settings
    if (view.menuPage === 'comfort') {
      add('Quality: ' + settings.quality, 'quality')
      add('Reduced motion: ' + (settings.reducedMotion ? 'on' : 'off'), 'motion')
      add('Contrast: ' + (settings.highContrast ? 'high' : 'standard'), 'contrast')
      add('Sound and progress', 'sound-options')
    } else if (view.menuPage === 'sound') {
      add(settings.muted ? 'Enable sound' : 'Mute sound', 'mute')
      add('Volume down', 'volume-down')
      add('Volume up', 'volume-up')
      if (!view.practice) add('Reset progress', 'reset')
    }
    add('Back to game', 'back')
    return {
      title: view.menuPage === 'help' ? 'Moonfall controls' : 'Table comfort',
      message:
        view.menuPage === 'help'
          ? 'Triggers flip. A/X launches; B/Y pauses. Point at Recover ball if stuck. Orbit is a ring, Moon a crescent, Aurora a star. Follow the lit route; shoot a rising ball into either raised crescent ramp.'
          : 'Changes apply to this run. Sound starts muted. Volume ' +
            Math.round(settings.volume * 100) +
            '%.',
      actions,
    }
  }
  if (view.practice) {
    add(
      view.runtimeStatus === 'running' ? 'Pause' : 'Resume practice',
      view.runtimeStatus === 'running' ? 'pause' : 'resume',
    )
    add('Restart practice', 'restart-practice')
    add('Finish practice', 'finish-practice')
    add('Comfort and sound', 'options')
    add('Help', 'help')
    return {
      title: 'Moonfall practice',
      message:
        'No saves or personal bests are changed. Launch, try the flippers, aim at the lit target and shoot either crescent ramp.',
      actions,
    }
  }
  if (view.status !== 'denied') {
    if (view.chosen && (view.status === 'error' || view.status === 'conflict' || view.serverChoice))
      add(
        view.runtimeStatus === 'running' ? 'Pause' : 'Continue without saving',
        view.runtimeStatus === 'running' ? 'pause' : 'continue-unsaved',
      )
    if (view.confirm) {
      add(
        view.confirm === 'new' ? 'Replace saved run' : 'Delete saved progress',
        'confirm-' + view.confirm,
      )
      add('Cancel', 'cancel')
    } else if (view.serverChoice) {
      add('Load server run', 'load-server')
      add('Replace server run', 'replace-server')
    } else if (view.status === 'error' || view.status === 'conflict') {
      add('Retry connection', 'retry')
      if (!view.chosen && view.status === 'error') add('Play without saving', 'play-unsaved')
    } else if (view.status !== 'loading') {
      if (view.runtimeStatus === 'running') add('Pause', 'pause')
      else if ((view.chosen || view.hasSaved) && view.runtimeStatus !== 'result')
        add(view.chosen ? 'Resume' : 'Resume saved run', 'resume')
      if (view.runtimeStatus !== 'running') add('New run', 'new')
      if (view.chosen) add('Save progress', 'save')
      if (view.runtimeStatus === 'running') add('Recover ball', 'recover')
      if (view.runtimeStatus === 'result') add('Reset progress', 'reset')
      if (!view.chosen) add('Guided practice', 'practice')
      add('Comfort and sound', 'options')
      add('Help', 'help')
    }
  }
  return {
    title: 'Moonfall Pinball',
    message:
      view.confirm === 'reset'
        ? 'Delete this saved run and personal best? This cannot be undone.'
        : view.confirm === 'new'
          ? 'Replace the current run? Your personal best and settings will carry over.'
          : `${view.message} Score ${view.state.score.toLocaleString()}. Best ${view.state.best.toLocaleString()}. ${missionSummary(view.state)}`,
    actions,
  }
}

function missionSummary(state: View['state']) {
  const mission = state.missionHits.findIndex((hits, index) => hits < MISSION_ROUTES[index].length)
  if (mission < 0) return 'Aurora finale complete.'
  const required = MISSION_REQUIREMENTS[mission]
  return `${MISSION_NAMES[mission]}. Step ${state.missionHits[mission] + 1}/${MISSION_ROUTES[mission].length}: ${MISSION_ROUTES[mission][state.missionHits[mission]]}. Ramps ${Math.min(state.features.ramps, required.ramps)}/${required.ramps}, returns ${Math.min(state.features.returns, required.returns)}/${required.returns}, skill shots ${Math.min(state.features.skillShots, required.skillShots)}/${required.skillShots}. Meet these achievements before the final route shot.`
}

export function MoonfallPanel({
  view,
  command,
  input,
  settings,
}: {
  view: View
  command: (command: string) => void
  input: (action: keyof MoonfallInput, pressed: boolean, source: string) => void
  settings: (settings: Partial<MoonfallSettings>) => void
}) {
  const menu = moonfallMenu(view)
  const mission = view.state.missionHits.findIndex(
    (hit, index) => hit < MISSION_ROUTES[index].length,
  )
  return (
    <section className="od-moonfall" aria-label="Moonfall Pinball controls">
      <h3>Moonfall Pinball</h3>
      {view.runtimeStatus === 'result' && <h4>Run finished</h4>}
      {view.practice && (
        <p>
          Practice:{' '}
          {view.state.nextBallId === 1
            ? 'Hold the left flipper and launch to aim for Orbit. Right aims at Aurora; both aim toward Moon.'
            : !view.state.features.skillShots
              ? 'Try a launch skill shot: hit a moving target within three seconds of launching.'
              : !view.state.features.ramps
                ? 'Shoot a rising ball into either ramp mouth, above the flippers. The raised crescent returns it to the opposite side.'
                : 'Follow the lit targets in order. Finish practice whenever ready for a saved run.'}
        </p>
      )}
      <p role="status">{menu.message}</p>
      <p className="od-moonfall-phase">
        {view.state.phase === 'ready'
          ? 'Ball ready — launch when ready.'
          : view.state.phase === 'playing'
            ? 'Ball in play.'
            : view.state.phase === 'complete'
              ? 'Aurora finale complete.'
              : 'All balls finished.'}
      </p>
      <p>
        Three balls. Complete each target route in order to reach the aurora finale. A completed
        mission earns an extra ball once per run.
      </p>
      <p>
        Targets: Orbit ○ · Moon ☾ · Aurora ★.{' '}
        {mission >= 0
          ? `Upcoming: ${MISSION_ROUTES[mission].slice(view.state.missionHits[mission], view.state.missionHits[mission] + 5).join(' → ')}. ${missionSummary(view.state)}`
          : 'Aurora finale complete!'}{' '}
        · Balls remaining: {view.state.ballsRemaining} · Recoveries: {view.state.recoveries}
      </p>
      <p>
        Skill shots: {view.state.features.skillShots} · Crescent ramps: {view.state.features.ramps}{' '}
        · Return lanes: {view.state.features.returns}
      </p>
      <div className="od-library-room__controls">
        {menu.actions.map((action) => (
          <button
            type="button"
            className="od-cbtn"
            key={action.action}
            disabled={action.disabled}
            onClick={() => command(action.action.slice('@moonfall-'.length))}
          >
            {action.label}
          </button>
        ))}
      </div>
      {view.status !== 'denied' && (
        <>
          <div className="od-library-room__controls" role="group" aria-label="Pinball inputs">
            {(['left', 'right', 'launch', 'recover'] as const).map((action) => {
              const release = () => input(action, false, 'panel-' + action)
              return (
                <button
                  key={action}
                  type="button"
                  className="od-cbtn"
                  onPointerDown={(event) => {
                    event.currentTarget.setPointerCapture?.(event.pointerId)
                    input(action, true, 'panel-' + action)
                  }}
                  onPointerUp={release}
                  onPointerCancel={release}
                  onLostPointerCapture={release}
                  onBlur={release}
                  onKeyDown={(event) => {
                    if ((event.key === ' ' || event.key === 'Enter') && !event.repeat) {
                      event.preventDefault()
                      input(action, true, 'panel-' + action)
                    }
                  }}
                  onKeyUp={(event) => {
                    if (event.key === ' ' || event.key === 'Enter') {
                      event.preventDefault()
                      release()
                    }
                  }}
                >
                  {action === 'left'
                    ? 'Left flipper'
                    : action === 'right'
                      ? 'Right flipper'
                      : action === 'launch'
                        ? 'Launch ball'
                        : 'Recover stuck ball'}
                </button>
              )
            })}
          </div>
          <details>
            <summary>How to play and comfort</summary>
            <p>
              Focus the room: Z or Left Arrow and X or Right Arrow control the flippers. Space
              launches; R recovers a stuck ball; Escape pauses. Mouse buttons or the buttons above
              work too. Gamepad shoulders control flippers, A launches, Start pauses, and the right
              stick button recovers. In a headset, use the triggers for flippers, A/X to launch and
              B/Y to pause.
            </p>
            <p>
              Leaving focus pauses play. Resume explicitly when ready. Your saves and personal best
              are private to your account; scores are not competitive or server verified.
            </p>
            <div className="od-library-room__controls">
              <label>
                Quality{' '}
                <select
                  value={view.state.settings.quality}
                  onChange={(event) =>
                    settings({ quality: event.target.value as MoonfallSettings['quality'] })
                  }
                >
                  {(['low', 'standard', 'high'] as const).map((value) => (
                    <option key={value}>{value}</option>
                  ))}
                </select>
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={view.state.settings.reducedMotion}
                  onChange={(event) => settings({ reducedMotion: event.target.checked })}
                />
                Reduced motion
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={view.state.settings.highContrast}
                  onChange={(event) => settings({ highContrast: event.target.checked })}
                />
                High contrast targets
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={view.state.settings.muted}
                  onChange={(event) => settings({ muted: event.target.checked })}
                />
                Mute sound
              </label>
              <label>
                Volume{' '}
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.05"
                  value={view.state.settings.volume}
                  onChange={(event) => settings({ volume: Number(event.target.value) })}
                />
              </label>
            </div>
          </details>
        </>
      )}
    </section>
  )
}
