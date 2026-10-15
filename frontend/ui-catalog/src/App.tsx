import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Button,
  DataTable,
  ERA_GLYPH_NAMES,
  ERA_HAND,
  FilterChipGroup,
  Modal,
  PageStatus,
  RailIcon,
  railIconPaths,
  sharedIconAliases,
} from '@oneirodex/ui'
import type { DataTableColumn } from '@oneirodex/ui'

const TOKEN_NAMES = [
  '--od-bg',
  '--od-surface',
  '--od-surface-2',
  '--od-text',
  '--od-text-muted',
  '--od-accent',
  '--od-accent-2',
  '--od-accent-contrast',
  '--od-border',
  '--od-success',
  '--od-warning',
  '--od-danger',
  '--od-info',
  '--od-focus-ring',
]

const rows = [
  { name: 'Button', exportName: 'Button', responsibility: 'Shared control', status: 'Available' },
  {
    name: 'DataTable',
    exportName: 'DataTable',
    responsibility: 'Shared table',
    status: 'Available',
  },
  {
    name: 'Modal',
    exportName: 'Modal',
    responsibility: 'Shared dialog shell',
    status: 'Available',
  },
  {
    name: 'PageStatus',
    exportName: 'PageStatus',
    responsibility: 'Shared loading / empty / error',
    status: 'Available',
  },
  {
    name: 'RailIcon',
    exportName: 'RailIcon',
    responsibility: 'Shared rail glyph renderer',
    status: 'Available',
  },
  {
    name: 'FilterChipGroup',
    exportName: 'FilterChipGroup',
    responsibility: 'Shared multi-select filters',
    status: 'Available',
  },
]

const FILTER_CATEGORIES = [
  { value: 'control', label: 'Controls' },
  { value: 'data', label: 'Data and status' },
  { value: 'navigation', label: 'Navigation' },
]

const ROW_CATEGORIES: Record<string, string> = {
  Button: 'control',
  DataTable: 'data',
  FilterChipGroup: 'control',
  Modal: 'control',
  PageStatus: 'data',
  RailIcon: 'navigation',
}

const columns: DataTableColumn[] = [
  { key: 'name', label: 'Name', sortable: true },
  { key: 'responsibility', label: 'Role', sortable: true },
  { key: 'status', label: 'Status', sortable: true },
]

const ERA_PREVIEWS = [
  { label: 'Pixel', era: 'wood_den_80s' },
  { label: 'Round', era: 'teen_bedroom_90s' },
  { label: 'Angle', era: 'media_center_00s' },
] as const

type IconPackManifest = {
  id: string
  name: string
  description: string
  icons: Record<string, string>
}

const iconPackManifests = import.meta.glob<IconPackManifest>(
  '../../../oneirodex/setup/icon_themes/*/manifest.json',
  { eager: true, import: 'default' },
)
const iconPackAssets = import.meta.glob<string>(
  '../../../oneirodex/setup/icon_themes/*/icons/*.svg',
  { eager: true, query: '?url', import: 'default' },
)
const iconPackAssetByKey = Object.fromEntries(
  Object.entries(iconPackAssets).flatMap(([path, url]) => {
    const match = path.match(/icon_themes\/([^/]+)\/icons\/([^/]+)\.svg$/)
    return match ? [[`${match[1]}/${match[2]}`, url]] : []
  }),
)
const ICON_PACK_ORDER = ['outline', 'filled', 'duotone', 'pixel', 'soft', 'mono']
const iconPacks = Object.values(iconPackManifests).sort(
  (a, b) => ICON_PACK_ORDER.indexOf(a.id) - ICON_PACK_ORDER.indexOf(b.id),
)

function parseRgb(value: string): [number, number, number] | null {
  const match = value.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i)
  if (match) return [Number(match[1]), Number(match[2]), Number(match[3])]
  const hex = value.trim().match(/^#([\da-f]{3}|[\da-f]{6})$/i)?.[1]
  if (!hex) return null
  const full = hex.length === 3 ? [...hex].map((c) => c + c).join('') : hex
  return [0, 2, 4].map((index) => parseInt(full.slice(index, index + 2), 16)) as [
    number,
    number,
    number,
  ]
}

function rgb(values: [number, number, number], alpha?: number) {
  return alpha == null ? `rgb(${values.join(' ')})` : `rgb(${values.join(' ')} / ${alpha})`
}

function mix(a: [number, number, number], b: [number, number, number], amount: number) {
  return a.map((value, index) => Math.round(value * (1 - amount) + b[index] * amount)) as [
    number,
    number,
    number,
  ]
}

function luminance([red, green, blue]: [number, number, number]) {
  const linear = [red, green, blue].map((part) => {
    const channel = part / 255
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
  })
  return linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722
}

function contrastRatio(a: [number, number, number], b: [number, number, number]) {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (light + 0.05) / (dark + 0.05)
}

function darkenToContrast(
  foreground: [number, number, number],
  background: [number, number, number],
  target = 4.5,
) {
  let result = foreground
  for (let step = 1; step <= 100 && contrastRatio(result, background) < target; step += 1) {
    result = mix(foreground, [0, 0, 0], step / 100)
  }
  return result
}

function deriveLightTokens(source: CSSStyleDeclaration): Record<string, string> {
  const read = (name: string) => parseRgb(source.getPropertyValue(name))
  const darkBg = read('--od-bg') ?? [11, 13, 16]
  const darkSurface = read('--od-surface') ?? darkBg
  const darkSurface2 = read('--od-surface-2') ?? darkSurface
  const darkText = read('--od-text') ?? [242, 244, 248]
  const darkMuted = read('--od-text-muted') ?? darkText
  const darkBorder = read('--od-border') ?? [80, 88, 98]
  const darkAccent = read('--od-accent') ?? [47, 214, 123]
  const lightBg = mix(darkText, darkBg, 0.04)
  const lightText = mix(darkBg, darkText, 0.04)
  const lightAccent = darkenToContrast(darkAccent, lightBg)
  const black: [number, number, number] = [0, 0, 0]
  const white: [number, number, number] = [255, 255, 255]
  const accentForeground =
    contrastRatio(black, lightAccent) >= contrastRatio(white, lightAccent) ? black : white
  const lightSuccess = darkenToContrast(read('--od-success') ?? [74, 222, 128], lightBg)
  const lightWarning = darkenToContrast(read('--od-warning') ?? [255, 201, 74], lightBg)
  const lightDanger = darkenToContrast(read('--od-danger') ?? [255, 107, 107], lightBg)
  const lightInfo = darkenToContrast(read('--od-info') ?? [90, 200, 250], lightBg)
  return {
    '--od-bg': rgb(lightBg),
    '--od-surface': rgb(mix(lightBg, darkSurface, 0.08)),
    '--od-surface-2': rgb(mix(lightBg, darkSurface2, 0.16)),
    '--od-text': rgb(lightText),
    '--od-text-muted': rgb(mix(lightText, darkMuted, 0.2)),
    '--od-border': rgb(mix(lightBg, darkBorder, 0.2)),
    '--od-accent': rgb(lightAccent),
    '--od-accent-2': rgb(darkenToContrast(read('--od-accent-2') ?? darkAccent, lightBg)),
    '--od-accent-contrast': rgb(accentForeground),
    '--od-success': rgb(lightSuccess),
    '--od-warning': rgb(lightWarning),
    '--od-danger': rgb(lightDanger),
    '--od-info': rgb(lightInfo),
    '--od-focus-ring': rgb(darkenToContrast(darkAccent, lightBg, 3)),
    colorScheme: 'light',
  }
}

function readTokenValue(name: string, element: HTMLElement | null) {
  if (!element) return '—'
  return getComputedStyle(element).getPropertyValue(name).trim() || '—'
}

export function App() {
  const [light, setLight] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [filterCategories, setFilterCategories] = useState<string[]>([])
  const [iconFilter, setIconFilter] = useState('')
  const paletteRef = useRef<HTMLElement>(null)
  const [tokenValues, setTokenValues] = useState<Record<string, string>>({})
  const lightTokens = useMemo(
    () => deriveLightTokens(getComputedStyle(document.documentElement)),
    [],
  )

  useEffect(() => {
    const target = paletteRef.current
    if (!target) return
    setTokenValues(
      Object.fromEntries(TOKEN_NAMES.map((name) => [name, readTokenValue(name, target)])),
    )
  }, [light])

  const icons = Object.keys(railIconPaths)
    .filter((name) => !sharedIconAliases[name])
    .sort()
  const aliasesFor = (name: string) =>
    Object.keys(sharedIconAliases).filter((alias) => sharedIconAliases[alias] === name)
  const visibleIcons = icons.filter((name) =>
    [name, ...aliasesFor(name)].some((key) => key.includes(iconFilter.trim().toLowerCase())),
  )
  const visibleRows =
    filterCategories.length === 0
      ? rows
      : rows.filter((row) => filterCategories.includes(ROW_CATEGORIES[row.exportName]))

  return (
    <main
      className={`catalog ${light ? 'catalog--light' : 'catalog--dark'}`}
      ref={paletteRef}
      style={light ? (lightTokens as React.CSSProperties) : undefined}
    >
      <header className="catalog__header">
        <div>
          <p className="catalog__eyebrow">Oneirodex · local developer tooling</p>
          <h1>UI catalog</h1>
          <p className="catalog__lede">
            Live specimens from the private <code>@oneirodex/ui</code> workspace and canonical theme
            tokens. This catalog is local tooling; it is not an externally published package.
          </p>
        </div>
        <div className="catalog__theme-control" aria-label="Preview palette">
          <span>Preview</span>
          <Button
            variant={light ? 'secondary' : 'primary'}
            onClick={() => setLight(false)}
            aria-pressed={!light}
          >
            Dark green
          </Button>
          <Button
            variant={light ? 'primary' : 'secondary'}
            onClick={() => setLight(true)}
            aria-pressed={light}
          >
            Light
          </Button>
        </div>
      </header>

      <section className="catalog__section" aria-labelledby="tokens-title">
        <div className="catalog__section-heading">
          <div>
            <p className="catalog__eyebrow">Source: od-tokens.css</p>
            <h2 id="tokens-title">Semantic tokens</h2>
          </div>
          <p>Values are read from the active catalog palette.</p>
        </div>
        <div className="catalog__swatches">
          {TOKEN_NAMES.map((name) => (
            <article className="catalog__swatch" key={name}>
              <span className="catalog__swatch-color" style={{ background: `var(${name})` }} />
              <code>{name}</code>
              <small>{tokenValues[name] || '…'}</small>
            </article>
          ))}
        </div>
      </section>

      <section className="catalog__section" aria-labelledby="buttons-title">
        <div className="catalog__section-heading">
          <div>
            <p className="catalog__eyebrow">Shared export: Button</p>
            <h2 id="buttons-title">Buttons</h2>
          </div>
          <p>Variants, sizes, and disabled state.</p>
        </div>
        <div className="catalog__button-grid">
          {(['default', 'primary', 'secondary', 'danger', 'ghost', 'quiet'] as const).map(
            (variant) => (
              <article className="catalog__specimen" key={variant}>
                <h3>{variant}</h3>
                <div className="catalog__button-row">
                  {(['sm', 'md', 'lg'] as const).map((size) => (
                    <Button key={size} variant={variant} size={size}>
                      {size}
                    </Button>
                  ))}
                  <Button variant={variant} disabled>
                    Disabled
                  </Button>
                </div>
              </article>
            ),
          )}
        </div>
      </section>

      <section className="catalog__section" aria-labelledby="icons-title">
        <div className="catalog__section-heading">
          <div>
            <p className="catalog__eyebrow">Shared export: RailIcon</p>
            <h2 id="icons-title">Rail icons</h2>
          </div>
          <p>
            {icons.length} keys from the shared React rail renderer. The eight era overrides are
            shown beside the shared drawings so reviewers can compare the active glyph hands.
          </p>
        </div>
        <label className="catalog__field" htmlFor="catalog-icon-filter">
          Find an icon
        </label>
        <input
          id="catalog-icon-filter"
          className="od-input catalog__input"
          type="search"
          value={iconFilter}
          onChange={(event) => setIconFilter(event.target.value)}
        />
        <div className="catalog__icon-grid">
          {visibleIcons.map((name) => (
            <article className="catalog__icon" key={name}>
              <RailIcon name={name} size={24} />
              <code>{name}</code>
              {aliasesFor(name).length ? (
                <small>Aliases: {aliasesFor(name).join(', ')}</small>
              ) : null}
              {ERA_GLYPH_NAMES.includes(name as (typeof ERA_GLYPH_NAMES)[number]) ? (
                <div className="catalog__icon-variants" aria-label={`${name} era variants`}>
                  {ERA_PREVIEWS.map(({ label, era }) => (
                    <div className="catalog__icon-variant" key={era}>
                      <RailIcon name={name} size={24} era={era} />
                      <small>{label}</small>
                    </div>
                  ))}
                </div>
              ) : (
                <small>Shared drawing · all eras</small>
              )}
            </article>
          ))}
          {!visibleIcons.length ? <p role="status">No icon keys match that search.</p> : null}
        </div>
        <p className="catalog__icon-note">
          Room-to-hand mapping:{' '}
          {Object.entries(ERA_HAND)
            .map(([room, hand]) => `${room.replaceAll('_', ' ')} → ${hand}`)
            .join(' · ')}
          . The next section previews the separate theme-pack SVG assets.
        </p>
      </section>

      <section className="catalog__section" aria-labelledby="icon-packs-title">
        <div className="catalog__section-heading">
          <div>
            <p className="catalog__eyebrow">Source: installed icon theme packs</p>
            <h2 id="icon-packs-title">Theme pack drawings</h2>
          </div>
          <p>
            {iconPacks.length} pack manifests; compare their declared drawings against the shared
            rail keys. Outline uses shared rail drawings where keys exist. The other packs draw
            their 17 declared icons; every other shared glyph keeps its standard outline shape.
          </p>
        </div>
        <div className="catalog__pack-list">
          {iconPacks.map((pack) => {
            const keys = Object.keys(pack.icons)
              .sort()
              .filter((name) => name.includes(iconFilter.trim().toLowerCase()))
            return (
              <details className="catalog__pack" key={pack.id} open={pack.id === 'outline'}>
                <summary>
                  <span>{pack.name}</span>
                  <small>
                    {keys.length} shown · {Object.keys(pack.icons).length} declared
                  </small>
                </summary>
                <p>{pack.description}</p>
                <div className="catalog__pack-grid">
                  {keys.map((name) => {
                    const asset = iconPackAssetByKey[`${pack.id}/${name}`]
                    return (
                      <article className="catalog__pack-icon" key={name}>
                        {asset ? (
                          <span
                            aria-hidden="true"
                            className="catalog__pack-glyph"
                            style={{
                              maskImage: `url("${asset}")`,
                              WebkitMaskImage: `url("${asset}")`,
                            }}
                          />
                        ) : (
                          <>
                            {railIconPaths[name] ? (
                              <RailIcon name={name} size={24} />
                            ) : (
                              <span className="catalog__pack-glyph-missing" aria-hidden="true">
                                ?
                              </span>
                            )}
                          </>
                        )}
                        <code>{name}</code>
                        {!asset && !railIconPaths[name] ? (
                          <small>Missing shared rail key</small>
                        ) : null}
                      </article>
                    )
                  })}
                  {!keys.length ? <p role="status">No pack keys match that search.</p> : null}
                </div>
              </details>
            )
          })}
        </div>
      </section>

      <section className="catalog__section catalog__two-column">
        <article className="catalog__panel" aria-labelledby="table-title">
          <div className="catalog__section-heading">
            <div>
              <p className="catalog__eyebrow">Shared export: DataTable</p>
              <h2 id="table-title">Sortable and searchable table</h2>
            </div>
          </div>
          <DataTable
            columns={columns}
            rows={visibleRows}
            getRowKey={(row) => row.exportName}
            caption="Shared UI package exports"
            scrollLabel="Shared export list"
            columnFilters
          />
        </article>
        <article className="catalog__panel" aria-labelledby="filter-title">
          <div className="catalog__section-heading">
            <div>
              <p className="catalog__eyebrow">Shared export: FilterChipGroup</p>
              <h2 id="filter-title">Applied filter example</h2>
            </div>
          </div>
          <p className="catalog__note">
            Multi-select chips apply immediately in this specimen. Features own query meaning and
            may keep draft values until their Apply action runs.
          </p>
          <FilterChipGroup
            label="Filter shared exports"
            options={FILTER_CATEGORIES}
            value={filterCategories}
            onChange={setFilterCategories}
            resultCount={visibleRows.length}
            resultCountLabel={(count) => `${count} matching shared exports`}
            onClear={() => setFilterCategories([])}
          />
        </article>
      </section>

      <section className="catalog__section" aria-labelledby="states-title">
        <div className="catalog__section-heading">
          <div>
            <p className="catalog__eyebrow">Shared export: PageStatus</p>
            <h2 id="states-title">Key states</h2>
          </div>
          <p>Loading, empty, and actionable error specimens.</p>
        </div>
        <div className="catalog__state-grid">
          <article className="catalog__panel">
            <h3>Loading</h3>
            <PageStatus inline loading loadingMessage="Loading library" />
          </article>
          <article className="catalog__panel">
            <h3>Empty</h3>
            <PageStatus emptyMessage="No matching games yet." />
          </article>
          <article className="catalog__panel">
            <h3>Error</h3>
            <PageStatus error={new Error('Catalog request failed')} inline />
          </article>
        </div>
      </section>

      <section className="catalog__section catalog__two-column">
        <article className="catalog__panel" aria-labelledby="modal-title">
          <div className="catalog__section-heading">
            <div>
              <p className="catalog__eyebrow">Shared export: Modal</p>
              <h2 id="modal-title">Dialog shell</h2>
            </div>
          </div>
          <p className="catalog__note">
            Opens a real shared portal with focus handling, Escape, and focus restoration.
          </p>
          <Button variant="primary" onClick={() => setModalOpen(true)}>
            Open modal preview
          </Button>
          <Modal
            open={modalOpen}
            onClose={() => setModalOpen(false)}
            label="Modal preview"
            className="catalog__modal"
            panelClassName="catalog__modal-panel"
            lockScroll
          >
            <h3>Shared modal shell</h3>
            <p>
              Use an accessible name and keep the dialog content specific to the owning feature.
            </p>
            <Button variant="secondary" onClick={() => setModalOpen(false)}>
              Close dialog
            </Button>
          </Modal>
        </article>
        <article className="catalog__panel" aria-labelledby="responsive-title">
          <div className="catalog__section-heading">
            <div>
              <p className="catalog__eyebrow">Responsive specimen</p>
              <h2 id="responsive-title">Content-driven layout</h2>
            </div>
          </div>
          <p>
            Resize the window: this section moves from two columns to one without widening the
            document.
          </p>
          <div className="catalog__responsive-sample">
            <div>Browse content</div>
            <div>Actions wrap with labels</div>
          </div>
        </article>
      </section>

      <footer className="catalog__footer">
        <strong>Package boundary:</strong> source is the private <code>@oneirodex/ui</code>{' '}
        workspace. External install, hosted assets, and the framework-neutral icon manifest require
        follow-up work.
      </footer>
    </main>
  )
}
