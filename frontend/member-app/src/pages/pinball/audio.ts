import type { MoonfallSettings, MoonfallState } from './model'

/** Original synthesized cues; no media downloads and no automatic audio activation. */
export function createMoonfallAudio(factory: () => AudioContext = () => new AudioContext()) {
  let context: AudioContext | null = null
  let disposed = false
  let previous: { score: number; balls: number; hits: number; phase: string } | null = null
  let lastCue = -Infinity
  const voices = new Set<OscillatorNode>()
  function silence() {
    voices.forEach((voice) => {
      try {
        voice.stop()
      } catch {
        /* already ended */
      }
    })
  }
  return {
    unlock(settings: MoonfallSettings) {
      if (disposed) return
      if (settings.muted || settings.volume === 0) {
        silence()
        return
      }
      try {
        context ??= factory()
        if (context.state === 'suspended') void context.resume().catch(() => {})
      } catch {
        /* Audio is optional; gameplay remains available. */
      }
    },
    observe(state: Readonly<MoonfallState>, status: string) {
      if (disposed) return
      const next = {
        score: state.score,
        balls: state.balls.length,
        hits: state.missionHits.reduce((a, b) => a + b, 0),
        phase: state.phase,
      }
      const old = previous
      previous = next
      if (status !== 'running' || state.settings.muted || state.settings.volume === 0) {
        silence()
        return
      }
      if (
        !old ||
        !context ||
        context.state !== 'running' ||
        voices.size >= 4 ||
        context.currentTime - lastCue < 0.075
      )
        return
      const pitch =
        next.hits > old.hits
          ? 880
          : next.score > old.score
            ? 523.25
            : next.balls > old.balls
              ? 330
              : next.balls < old.balls
                ? 130.81
                : 0
      if (!pitch) return
      try {
        const oscillator = context.createOscillator()
        const envelope = context.createGain()
        const now = context.currentTime
        oscillator.type = 'sine'
        oscillator.frequency.setValueAtTime(pitch, now)
        oscillator.frequency.exponentialRampToValueAtTime(pitch * 0.8, now + 0.16)
        envelope.gain.setValueAtTime(Math.min(0.12, state.settings.volume * 0.12), now)
        envelope.gain.exponentialRampToValueAtTime(0.0001, now + 0.18)
        oscillator.connect(envelope)
        envelope.connect(context.destination)
        oscillator.onended = () => {
          voices.delete(oscillator)
          oscillator.disconnect()
          envelope.disconnect()
        }
        voices.add(oscillator)
        lastCue = now
        oscillator.start(now)
        oscillator.stop(now + 0.2)
      } catch {
        /* A closed or unavailable device must not stop the room. */
      }
    },
    dispose() {
      if (disposed) return
      disposed = true
      silence()
      voices.clear()
      previous = null
      if (context) void context.close().catch(() => {})
      context = null
    },
  }
}
