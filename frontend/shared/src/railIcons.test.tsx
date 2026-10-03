import { render } from '@testing-library/react'
import { expect, test } from 'vitest'
import { RailIcon, railIconPaths, RAIL_VIEWBOX } from './railIcons'
import { ERA_GLYPH_NAMES, ERA_HAND, eraGlyph, themeUsesEraGlyphs } from './railIconsEra'

test('every rail destination has a glyph, including the one admin used to miss', () => {
  // `ways-to-play` existed only in the member copy before these were merged —
  // the drift that motivated the move.
  expect(railIconPaths['ways-to-play']).toBeTruthy()
  expect(Object.keys(railIconPaths).length).toBeGreaterThanOrEqual(30)
})

test('admin sub-section glyphs exist', () => {
  for (const name of [
    'scan',
    'tools',
    'unmatched',
    'filter',
    'art',
    'plugins',
    'chart',
    'danger',
    'storage',
    'emulators',
    'themes',
    'layout',
    'attract',
    'ai',
    'quality',
    'reference',
    'matching',
    'mail',
    'metadata',
    'identity',
    'voice',
    'stores',
    'remote',
    'server',
  ]) {
    expect(railIconPaths[name], name).toBeTruthy()
  }
})

test('renders a padded viewBox so a 2px edge stroke is not sliced in half', () => {
  const { container } = render(<RailIcon name="activity" />)
  const svg = container.querySelector('svg')
  expect(svg).toBeTruthy()
  expect(svg!.getAttribute('viewBox')).toBe(RAIL_VIEWBOX)
  expect(svg!.getAttribute('data-icon')).toBe('activity')
  // currentColor throughout, so the icon-pack tokens restyle per theme.
  expect(svg!.getAttribute('stroke')).toBe('currentColor')
})

test('an unknown id renders nothing rather than a dot', () => {
  const { container } = render(<RailIcon name="no-such-destination" />)
  expect(container.querySelector('svg')).toBeNull()
})

test('size drives both dimensions', () => {
  const { container } = render(<RailIcon name="activity" size={32} />)
  const svg = container.querySelector('svg')
  expect(svg!.getAttribute('width')).toBe('32')
  expect(svg!.getAttribute('height')).toBe('32')
})

describe('era-drawn glyphs (E4)', () => {
  afterEach(() => {
    document.documentElement.removeAttribute('data-theme')
    document.documentElement.removeAttribute('data-era')
  })

  test('every hand draws every era glyph name', () => {
    for (const era of Object.keys(ERA_HAND)) {
      for (const name of ERA_GLYPH_NAMES) {
        expect(eraGlyph(name, era), `${era}/${name}`).toBeTruthy()
      }
    }
    expect(eraGlyph('wishlist', 'wood_den_80s')).toBeNull()
    expect(eraGlyph('discover', 'not-an-era')).toBeNull()
  })

  test('a decade room draws the rail in its own hand', () => {
    document.documentElement.setAttribute('data-theme', 'era-80s')
    document.documentElement.setAttribute('data-era', 'wood_den_80s')
    const { container } = render(<RailIcon name="favorites" />)
    const svg = container.querySelector('svg')!
    expect(svg.getAttribute('data-era-hand')).toBe('wood_den_80s')
    // The 8-bit heart is a stepped, filled path — no curves at all.
    expect(container.innerHTML).not.toMatch(/[Aa]\d/) // no arc commands
    expect(container.querySelector('path[fill="currentColor"]')).toBeTruthy()
  })

  test('a colour cabinet and the default theme keep the shared drawing', () => {
    document.documentElement.setAttribute('data-theme', 'aurora')
    document.documentElement.setAttribute('data-era', 'arcade_cabinet')
    const { container } = render(<RailIcon name="favorites" />)
    expect(container.querySelector('svg')!.hasAttribute('data-era-hand')).toBe(false)
    expect(themeUsesEraGlyphs('default')).toBe(false)
    expect(themeUsesEraGlyphs('console-cartridge')).toBe(true)
  })

  test('era={null} forces the shared drawing; era="…" forces a hand', () => {
    document.documentElement.setAttribute('data-theme', 'era-desk')
    document.documentElement.setAttribute('data-era', 'desk')
    const shared = render(<RailIcon name="chat" era={null} />).container
    expect(shared.querySelector('svg')!.hasAttribute('data-era-hand')).toBe(false)
    const forced = render(<RailIcon name="chat" era="teen_bedroom_90s" />).container
    expect(forced.querySelector('svg')!.getAttribute('data-era-hand')).toBe('teen_bedroom_90s')
  })
})
