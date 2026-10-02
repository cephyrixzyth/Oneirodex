/**
 * Store / ownership filters for the catalog (LIB-02).
 *
 * Maps onto the browse params the backend already honours:
 *   ownership=owned|unrecorded, store=steam,gog, store_match=any|all.
 * Like the other chips these apply immediately. `store_match` is only sent
 * when it changes the answer (two or more stores, "owned" mode), because on
 * its own `all` would mean "owned in any store" to the server.
 *
 * "Not recorded" is worded with care: it means no linked store or imported
 * list mentions the game, which is not proof the member does not own it.
 */
type Option = { id: string; name: string }
type Props = {
  filters: Record<string, string | undefined>
  stores: Option[]
  onApply: (next: Record<string, unknown>) => void
  clean: (filters: Record<string, string | undefined>) => Record<string, unknown>
  t?: (key: string, vars?: Record<string, unknown>) => string
}

type Ownership = '' | 'owned' | 'unrecorded'

export function parseStores(value: string | undefined): string[] {
  return (value || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
}

export function ownershipFilters(
  filters: Record<string, string | undefined>,
  stores: string[],
  ownership: Ownership,
  mode: 'any' | 'all',
) {
  const next: Record<string, string | undefined> = { ...filters }
  delete next.store
  delete next.store_match
  delete next.ownership
  if (ownership) next.ownership = ownership
  if (ownership && stores.length) next.store = stores.join(',')
  if (ownership === 'owned' && stores.length >= 2 && mode === 'all') next.store_match = 'all'
  return next
}

export function OwnershipFilterControls({
  filters,
  stores,
  onApply,
  clean,
  t = (key) => key,
}: Props) {
  const selected = parseStores(filters.store)
  const ownership: Ownership =
    filters.ownership === 'owned' || filters.ownership === 'unrecorded'
      ? filters.ownership
      : selected.length
        ? 'owned'
        : ''
  const mode = filters.store_match === 'all' ? 'all' : 'any'
  const commit = (nextStores: string[], nextOwnership: Ownership, nextMode: 'any' | 'all') =>
    onApply(clean(ownershipFilters(filters, nextStores, nextOwnership, nextMode)))

  const shows: [Ownership, string, string][] = [
    ['', t('All games'), t('Ignore store ownership')],
    ['owned', t('Owned'), t('Recorded as owned in your linked stores or imports')],
    [
      'unrecorded',
      t('Not recorded'),
      t('No linked store or import lists it. This is not proof you do not own it.'),
    ],
  ]

  return (
    <fieldset className="library-filters__signals library-filters__ownership">
      <legend>{t('Ownership')}</legend>
      <div
        className="od-cbtn-group od-cbtn-group--fill"
        role="group"
        aria-label={t('Show games by ownership')}
      >
        {shows.map(([value, label, title]) => (
          <button
            key={value || 'all'}
            type="button"
            className={`od-cbtn${ownership === value ? ' is-on' : ''}`}
            aria-pressed={ownership === value}
            title={title}
            onClick={() => commit(value ? selected : [], value, mode)}
          >
            {label}
          </button>
        ))}
      </div>
      {ownership && stores.length ? (
        <div className="od-badge-filter-chips" role="group" aria-label={t('Stores')}>
          {stores.map((store) => {
            const active = selected.includes(store.id)
            return (
              <button
                key={store.id}
                type="button"
                className={`od-badge-filter-chip${active ? ' is-active' : ''}`}
                aria-pressed={active}
                onClick={() =>
                  commit(
                    active ? selected.filter((s) => s !== store.id) : [...selected, store.id],
                    ownership,
                    mode,
                  )
                }
              >
                {store.name}
              </button>
            )
          })}
        </div>
      ) : null}
      {ownership === 'owned' && selected.length >= 2 ? (
        <div
          className="od-cbtn-group od-cbtn-group--fill"
          role="group"
          aria-label={t('Match stores')}
        >
          {(
            [
              ['any', t('In any selected store')],
              ['all', t('In every selected store')],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              className={`od-cbtn${mode === value ? ' is-on' : ''}`}
              aria-pressed={mode === value}
              onClick={() => commit(selected, ownership, value)}
            >
              {label}
            </button>
          ))}
        </div>
      ) : null}
      {ownership === 'unrecorded' ? (
        <p className="library-filters__hint">
          {selected.length
            ? t('Games no selected store has recorded. Not proof you do not own them.')
            : t('Games no linked store or import has recorded. Not proof you do not own them.')}
        </p>
      ) : null}
    </fieldset>
  )
}
