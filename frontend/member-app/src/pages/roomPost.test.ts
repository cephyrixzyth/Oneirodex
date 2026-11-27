import { expect, it } from 'vitest'
import { ROOM_QUALITIES, roomEffects, roomPixelRatio } from './roomPost'

it('keeps Low as a direct render and saves ambient occlusion for High', () => {
  expect(roomEffects('low')).toEqual({
    composer: false,
    bloom: false,
    msaa: 0,
    ambientOcclusion: false,
  })
  expect(roomEffects('standard')).toMatchObject({
    composer: true,
    bloom: true,
    ambientOcclusion: false,
  })
  expect(roomEffects('high')).toMatchObject({ composer: true, msaa: 4, ambientOcclusion: true })
  expect(ROOM_QUALITIES).toEqual(['low', 'standard', 'high'])
})

it('never renders above the device pixel ratio', () => {
  expect(roomPixelRatio('high', 3)).toBe(1.6)
  expect(roomPixelRatio('standard', 1)).toBe(1)
  expect(roomPixelRatio('low', 2)).toBe(0.6)
  expect(roomPixelRatio('standard', 0)).toBe(1)
})
