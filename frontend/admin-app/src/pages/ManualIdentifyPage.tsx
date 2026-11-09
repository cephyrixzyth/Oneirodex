import { Button, PageStatus } from '@oneirodex/ui'
import { Page } from '../components/Page'
import './ManualIdentifyPage.css'
import { TAXONOMIES, providerName } from './manualIdentifyTypes'
import { useManualIdentify } from './useManualIdentify'

export function ManualIdentifyPage() {
  const {
    editing,
    options,
    loadError,
    candidates,
    providerNotice,
    providerError,
    searchBusy,
    searchSource,
    form,
    saving,
    saveError,
    fieldErrors,
    scanRunning,
    linkQuery,
    setLinkQuery,
    linkHits,
    setLinkHits,
    linkSelected,
    setLinkSelected,
    linkSearching,
    linkBusy,
    linkError,
    setLinkError,
    linkSearched,
    setLinkSearched,
    activeTab,
    setActiveTab,
    customIdMode,
    nameInputRef,
    setField,
    search,
    searchProvider,
    chooseProvider,
    choose,
    submit,
    fromUnmatched,
    hasScanContext,
    identifyFieldsValid,
    tabs,
    onTabKeyDown,
    loadIgdbId,
    addNonCatalogGame,
    searchExistingGames,
    linkExistingGame,
  } = useManualIdentify()

  return (
    <Page
      title={
        editing ? 'Edit game entry' : fromUnmatched ? 'Identify unmatched folder' : 'Identify game'
      }
      lede={
        editing
          ? 'Update metadata for an existing library title.'
          : fromUnmatched
            ? 'Match a scanned folder to catalog metadata or an existing library game.'
            : 'Search providers, set path metadata, and save into the library.'
      }
      actions={
        <Button
          variant="primary"
          size="lg"
          type="submit"
          form="od-manual-identify-form"
          disabled={saving || !options || Boolean(loadError) || scanRunning || !identifyFieldsValid}
        >
          {saving ? 'Saving…' : editing ? 'Save changes' : 'Save'}
        </Button>
      }
      className="od-manual-identify"
    >
      {hasScanContext ? (
        <div className="od-admin-actions-row">
          <a
            className="od-cbtn"
            href={
              fromUnmatched
                ? '/scan_management?active_tab=unmatched'
                : '/scan_management?active_tab=manual'
            }
          >
            Back to scan review
          </a>
        </div>
      ) : null}
      {loadError ? (
        <PageStatus announcement="alert" className="od-manual-identify__error">
          {loadError} <Button onClick={() => window.location.reload()}>Retry</Button>
        </PageStatus>
      ) : null}
      {scanRunning ? (
        <PageStatus announcement="status" className="od-manual-identify__error">
          A scan is running. Editing is paused until it finishes.
        </PageStatus>
      ) : null}
      {saveError ? (
        <PageStatus announcement="alert" className="od-manual-identify__error">
          {saveError}
        </PageStatus>
      ) : null}
      <section
        className="od-admin-panel od-manual-identify__library-panel"
        aria-label="Library selection"
      >
        <div className="od-manual-identify__library">
          <label className="od-admin-field">
            Library
            <select
              className="od-admin-input"
              value={form.library_uuid}
              onChange={(event) => setField('library_uuid', event.target.value)}
              required
              disabled={!options || saving}
            >
              {options?.libraries.map((row) => (
                <option key={row.uuid} value={row.uuid}>
                  {row.name} · {row.platform_name}
                </option>
              ))}
            </select>
          </label>
          <p className="od-manual-identify__library-summary">
            Platform:{' '}
            {options?.libraries.find((row) => row.uuid === form.library_uuid)?.platform_name || '—'}
          </p>
        </div>
      </section>
      <section className="od-admin-panel od-manual-identify__essential" aria-label="Game identity">
        <div className="od-manual-identify__id">
          <label className="od-admin-field">
            IGDB ID
            <input
              className="od-admin-input"
              type="number"
              min="1"
              value={form.igdb_id}
              onChange={(event) => setField('igdb_id', event.target.value)}
              required
              readOnly={customIdMode}
              aria-describedby="od-manual-identify-igdb-help"
            />
          </label>
          <div className="od-admin-actions-row">
            <Button
              variant="primary"
              size="lg"
              type="button"
              onClick={() => void loadIgdbId()}
              aria-label="Search IGDB by ID"
              disabled={searchBusy || customIdMode}
            >
              Search IGDB
            </Button>
            <span id="od-manual-identify-igdb-help" className="od-admin-lede od-admin-lede--flush">
              Enter the IGDB ID of the game.
            </span>
          </div>
        </div>
      </section>
      <div className="od-manual-identify__custom-id-action">
        <Button size="lg" type="button" onClick={() => void addNonCatalogGame()}>
          Add non-catalog game
        </Button>
      </div>
      <section
        className="od-admin-panel od-manual-identify__search-panel"
        aria-label="Metadata search"
      >
        <form
          className="od-manual-identify__search"
          onSubmit={(event) => {
            event.preventDefault()
            void search()
          }}
        >
          <label className="od-admin-field">
            Name
            <input
              className="od-admin-input"
              value={form.name}
              ref={nameInputRef}
              onChange={(event) => setField('name', event.target.value)}
            />
          </label>
          <div
            className="od-manual-identify__providers"
            role="group"
            aria-label="Metadata provider searches"
          >
            <Button variant="primary" size="lg" type="submit" disabled={customIdMode || searchBusy}>
              {searchBusy ? `Searching ${searchSource}…` : 'Search IGDB'}
            </Button>
            {['steam', 'gog', 'rawg', 'mobygames', 'thegamesdb'].map((source) => (
              <Button
                key={source}
                variant="primary"
                size="lg"
                type="button"
                onClick={() => void searchProvider(source)}
                disabled={searchBusy}
              >
                Search {providerName(source)}
              </Button>
            ))}
          </div>
        </form>
        {providerNotice ? (
          <PageStatus announcement="status" className="od-manual-identify__provider-note">
            {providerNotice}
          </PageStatus>
        ) : null}
        {providerError ? (
          <PageStatus announcement="alert" className="od-manual-identify__error">
            {providerError}
          </PageStatus>
        ) : null}
        {candidates.length ? (
          <ul className="od-manual-identify__results" aria-label={`${searchSource} matches`}>
            {candidates.map((row) => (
              <li key={row.id || row.url || row.name}>
                <span>
                  {row.name} · {searchSource} {row.id ? `#${row.id}` : ''}
                </span>
                <Button
                  type="button"
                  onClick={() => (searchSource === 'IGDB' ? choose(row) : void chooseProvider(row))}
                >
                  Use this match
                </Button>
              </li>
            ))}
          </ul>
        ) : null}
      </section>
      <section className="od-admin-panel od-manual-identify__path-panel" aria-label="Game location">
        <label className="od-admin-field od-manual-identify__path">
          Full disk path
          <input
            className="od-admin-input"
            value={form.full_disk_path}
            onChange={(event) => setField('full_disk_path', event.target.value)}
            required
          />
        </label>
      </section>
      <form
        className="od-admin-panel od-manual-identify__form"
        id="od-manual-identify-form"
        onSubmit={submit}
      >
        <div
          className="od-manual-identify__tabs"
          role="tablist"
          aria-label="Game metadata sections"
          onKeyDown={onTabKeyDown}
        >
          {tabs.map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              id={`od-identify-tab-${id}`}
              aria-controls={`od-identify-panel-${id}`}
              aria-selected={activeTab === id}
              tabIndex={activeTab === id ? 0 : -1}
              className={`od-manual-identify__tab${activeTab === id ? ' is-active' : ''}`}
              onClick={() => setActiveTab(id)}
            >
              {label}
            </button>
          ))}
        </div>
        <section
          id="od-identify-panel-about"
          role="tabpanel"
          aria-labelledby="od-identify-tab-about"
          hidden={activeTab !== 'about'}
        >
          <label className="od-admin-field">
            Summary
            <textarea
              className="od-admin-input"
              rows={4}
              value={form.summary}
              onChange={(event) => setField('summary', event.target.value)}
            />
          </label>
          <label className="od-admin-field">
            Storyline
            <textarea
              className="od-admin-input"
              rows={4}
              value={form.storyline}
              onChange={(event) => setField('storyline', event.target.value)}
            />
          </label>
          <div className="od-manual-identify__grid">
            <label className="od-admin-field">
              Developer
              <input
                className="od-admin-input"
                value={form.developer}
                onChange={(event) => setField('developer', event.target.value)}
              />
            </label>
            <label className="od-admin-field">
              Publisher
              <input
                className="od-admin-input"
                value={form.publisher}
                onChange={(event) => setField('publisher', event.target.value)}
              />
            </label>
          </div>
        </section>
        <section
          id="od-identify-panel-release"
          role="tabpanel"
          aria-labelledby="od-identify-tab-release"
          hidden={activeTab !== 'release'}
        >
          <div className="od-manual-identify__grid">
            <label className="od-admin-field">
              First release date
              <input
                className="od-admin-input"
                type="date"
                value={form.first_release_date}
                onChange={(event) => setField('first_release_date', event.target.value)}
              />
            </label>
            <label className="od-admin-field">
              Aggregated rating
              <input
                className="od-admin-input"
                type="number"
                min="0"
                max="100"
                step="any"
                value={form.aggregated_rating}
                onChange={(event) => setField('aggregated_rating', event.target.value)}
              />
            </label>
            <label className="od-admin-field">
              Category
              <select
                className="od-admin-input"
                value={form.category}
                onChange={(event) => setField('category', event.target.value)}
              >
                <option value="">Select category</option>
                {options?.categories.map((row) => (
                  <option key={row.value} value={row.value}>
                    {row.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="od-admin-field">
              Status
              <select
                className="od-admin-input"
                value={form.status}
                onChange={(event) => setField('status', event.target.value)}
              >
                <option value="">Select status</option>
                {options?.statuses.map((row) => (
                  <option key={row.value} value={row.value}>
                    {row.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="od-admin-field">
              Item kind
              <select
                className="od-admin-input"
                value={form.item_kind}
                onChange={(event) => setField('item_kind', event.target.value)}
              >
                <option value="">Automatic</option>
                {['game', 'experience', 'emulator', 'tool'].map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </section>
        <section
          id="od-identify-panel-links"
          role="tabpanel"
          aria-labelledby="od-identify-tab-links"
          hidden={activeTab !== 'links'}
        >
          <div className="od-manual-identify__grid">
            <label className="od-admin-field">
              Website
              <input
                className="od-admin-input"
                type="url"
                value={form.url}
                onChange={(event) => setField('url', event.target.value)}
              />
            </label>
            <label className="od-admin-field">
              Video URLs
              <input
                className="od-admin-input"
                value={form.video_urls}
                onChange={(event) => setField('video_urls', event.target.value)}
              />
            </label>
          </div>
          <details className="od-manual-identify__provider-links">
            <summary>Provider links</summary>
            <div className="od-manual-identify__grid">
              {[
                ['steam', 'Steam'],
                ['gog', 'GOG'],
                ['epicgames', 'Epic Games'],
                ['itch', 'itch.io'],
                ['rawg', 'RAWG'],
                ['mobygames', 'MobyGames'],
                ['thegamesdb', 'TheGamesDB'],
                ['official', 'Official site'],
                ['wikipedia', 'Wikipedia'],
              ].map(([key, label]) => (
                <label className="od-admin-field" key={key}>
                  {label}
                  <input
                    className="od-admin-input"
                    type="url"
                    value={form.provider_urls[key] || ''}
                    onChange={(event) =>
                      setField('provider_urls', {
                        ...form.provider_urls,
                        [key]: event.target.value,
                      })
                    }
                    placeholder="https://…"
                  />
                </label>
              ))}
            </div>
          </details>
        </section>
        <section
          id="od-identify-panel-taxonomy"
          role="tabpanel"
          aria-labelledby="od-identify-tab-taxonomy"
          hidden={activeTab !== 'taxonomy'}
        >
          {TAXONOMIES.map(([key, label, field]) => (
            <fieldset className="od-manual-identify__taxonomy" key={key}>
              <legend>{label}</legend>
              {options?.taxonomies[key]?.map((row) => (
                <label key={row.id}>
                  <input
                    type="checkbox"
                    checked={form[field].includes(row.id)}
                    onChange={(event) =>
                      setField(
                        field,
                        event.target.checked
                          ? [...form[field], row.id]
                          : form[field].filter((id: number) => id !== row.id),
                      )
                    }
                  />{' '}
                  {row.name}
                </label>
              ))}
            </fieldset>
          ))}
        </section>
        {Object.keys(fieldErrors).length ? (
          <ul className="od-manual-identify__error-list" aria-label="Field validation errors">
            {Object.entries(fieldErrors).map(([field, message]) => (
              <li key={field}>
                <strong>{field.replaceAll('_', ' ')}:</strong> {message}
              </li>
            ))}
          </ul>
        ) : null}
      </form>
      <section className="od-admin-panel" aria-labelledby="od-link-existing-title">
        <h2 id="od-link-existing-title">Or link to an existing library game</h2>
        <p className="od-admin-lede">
          Search your library and choose a game to link this folder to instead of adding a new one.
        </p>
        <form className="od-admin-panel__toolbar" onSubmit={searchExistingGames}>
          <label className="od-admin-field">
            Search existing games
            <input
              className="od-admin-input"
              value={linkQuery}
              onChange={(event) => {
                setLinkQuery(event.target.value)
                setLinkHits([])
                setLinkSelected(null)
                setLinkError('')
                setLinkSearched(false)
              }}
              disabled={linkSearching || linkBusy}
              maxLength={100}
            />
          </label>
          <Button
            className="od-btn--secondary"
            type="submit"
            disabled={linkQuery.trim().length < 2 || linkSearching || linkBusy}
          >
            {linkSearching ? 'Searching…' : 'Search existing games'}
          </Button>
        </form>
        {linkError ? (
          <PageStatus error={linkError} errorMessage="Unable to link this folder." />
        ) : null}
        {linkHits.length ? (
          <div role="group" aria-label="Existing game search results">
            {linkHits.map((game) => (
              <Button
                key={game.uuid}
                type="button"
                className={
                  linkSelected?.uuid === game.uuid ? 'od-btn--accent' : 'od-btn--secondary'
                }
                aria-pressed={linkSelected?.uuid === game.uuid}
                onClick={() => setLinkSelected(game)}
                disabled={linkBusy}
              >
                {game.name}
                {game.full_disk_path ? ` · ${game.full_disk_path}` : ''}
              </Button>
            ))}
          </div>
        ) : null}
        {linkSearched && !linkHits.length ? (
          <PageStatus announcement="status">No existing games matched that search.</PageStatus>
        ) : null}
        <div className="od-admin-panel__toolbar">
          <Button
            className="od-btn--accent"
            type="button"
            onClick={() => void linkExistingGame()}
            disabled={!form.full_disk_path || !form.library_uuid || !linkSelected || linkBusy}
          >
            {linkBusy ? 'Linking…' : 'Link selected game'}
          </Button>
        </div>
      </section>
    </Page>
  )
}
