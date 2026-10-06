import { useEffect, useState, type KeyboardEvent } from 'react'
import { getJson } from '../api/adminApi'
import { Page } from '../components/Page'
import { SETTINGS_GROUPS } from '../components/navConfig'
import { RailIcon } from '../components/railIcons'

interface ModuleStatusEntry {
  on?: boolean
  label?: string
  detail?: string
}

function ModuleBadge({ status }: { status?: ModuleStatusEntry | null }) {
  if (!status) return null
  const on = Boolean(status.on)
  return (
    <span
      className={`od-settings-badge settings-shell-badge settings-shell-badge--${on ? 'on' : 'off'}`}
      data-testid="settings-module-badge"
    >
      {status.label || (on ? 'On' : 'Off')}
      {status.detail ? ` · ${status.detail}` : ''}
    </span>
  )
}

export function SettingsPage() {
  const [moduleStatus, setModuleStatus] = useState<Record<string, ModuleStatusEntry> | null>(null)
  const [section, setSection] = useState(SETTINGS_GROUPS[0]?.id || '')

  function onTabKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const current = SETTINGS_GROUPS.findIndex((group) => group.id === section)
    let next = -1
    if (event.key === 'ArrowRight') next = (current + 1) % SETTINGS_GROUPS.length
    if (event.key === 'ArrowLeft')
      next = (current - 1 + SETTINGS_GROUPS.length) % SETTINGS_GROUPS.length
    if (event.key === 'Home') next = 0
    if (event.key === 'End') next = SETTINGS_GROUPS.length - 1
    if (next < 0 || current < 0) return
    event.preventDefault()
    setSection(SETTINGS_GROUPS[next].id)
    event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next]?.focus()
  }

  useEffect(() => {
    getJson('/api/settings/module-status')
      .then((data) => setModuleStatus(data && typeof data === 'object' ? data : null))
      // A failed badge fetch must not blank the hub — the links are the page.
      .catch(() => setModuleStatus(null))
  }, [])

  return (
    <Page title="Settings" lede="Server modules, matching policy, presentation, and extensions.">
      <div
        className="od-admin-tabs"
        role="tablist"
        aria-label="Settings sections"
        onKeyDown={onTabKeyDown}
      >
        {SETTINGS_GROUPS.map((group) => (
          <button
            key={group.id}
            type="button"
            role="tab"
            id={`settings-tab-${group.id}`}
            aria-controls={`settings-panel-${group.id}`}
            aria-selected={section === group.id}
            tabIndex={section === group.id ? 0 : -1}
            className={`od-admin-tabs__tab${section === group.id ? ' is-active' : ''}`}
            onClick={() => setSection(group.id)}
          >
            <RailIcon name={group.icon} size={16} /> {group.title}
          </button>
        ))}
      </div>
      {SETTINGS_GROUPS.map((group) =>
        section === group.id ? (
          <section
            id={`settings-panel-${group.id}`}
            role="tabpanel"
            aria-labelledby={`settings-tab-${group.id}`}
            key={group.id}
            className="od-admin-panel od-settings"
          >
            <h2 className="od-settings-group__title">
              <RailIcon name={group.icon} size={16} /> {group.title} settings
            </h2>
            <ul className="od-settings-list">
              {group.items.map((item) => (
                <li key={item.to}>
                  <a className="od-settings-row" href={item.to}>
                    <span className="od-settings-row__title">
                      <RailIcon name={item.icon} size={16} /> {item.title}
                    </span>
                    {item.statusKey ? (
                      <ModuleBadge status={moduleStatus?.[item.statusKey]} />
                    ) : null}
                    <span className="od-settings-row__blurb">{item.blurb}</span>
                  </a>
                </li>
              ))}
            </ul>
          </section>
        ) : null,
      )}
    </Page>
  )
}
