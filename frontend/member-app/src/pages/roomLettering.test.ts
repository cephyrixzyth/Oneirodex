import { expect, it } from 'vitest'
import { instrumentLabelLayout } from './roomLettering'

it('fits the actual in-world tutorial and full current-route requirements in the mounted display', () => {
  const messages = [
    'Triggers flip. A/X launches; B/Y pauses. Point at Recover ball if stuck. Orbit is a ring, Moon a crescent, Aurora a star. Follow the lit route; shoot a rising ball into either raised crescent ramp.',
    'Progress could not be saved. Your current run is still in memory. Score 999,999. Best 999,999. Establish orbit. Step 18/18: orbit. Ramps 0/1, returns 0/2, skill shots 0/1. Meet these achievements before the final route shot.',
  ]
  for (const message of messages) {
    const result = instrumentLabelLayout(
      'Moonfall controls',
      message,
      800,
      322,
      (text, size) => text.length * size * 0.6,
    )
    expect(result.clipped).toBe(false)
    expect(
      result.lines
        .filter((line) => line.kind === 'body')
        .map((line) => line.text)
        .join(' '),
    ).toBe(message)
    expect(result.bodySize).toBeGreaterThanOrEqual(24)
    expect(result.lines.every((line) => line.y <= 316)).toBe(true)
  }
})
