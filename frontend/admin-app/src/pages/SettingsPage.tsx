import { useEffect, useState } from 'react'
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
  // Grouped rows, not a card grid (UX-C9): cards forced every module to the
  // same visual weight and spread a short list over a lot of empty space.
  //
  // One sheet, not four stacked `.od-admin-panel`s — nested glass on this hub
  // was the same "tables in tables" look UID-031 flattened on Libraries.
  //
  // The on/off badges are the Jinja hub's, restored: the template rendered them
  // from a `module_status` variable, and when the body moved to React the
  // variable kept being computed with nothing left to read it. They sit beside
  // the title, not inside the title column — that 13rem slot was clipping
  // "Scan / match policy" plus the pill.
  const [moduleStatus, setModuleStatus] = useState<Record<string, ModuleStatusEntry> | null>(null)

  useEffect(() => {
    getJson('/api/settings/module-status')
      .then((data) => setModuleStatus(data && typeof data === 'object' ? data : null))
      // A failed badge fetch must not blank the hub — the links are the page.
      .catch(() => setModuleStatus(null))
  }, [])

  return (
    <Page title="Settings" lede="Server modules, matching policy, presentation, and extensions.">
      <div className="od-admin-panel od-settings">
        {SETTINGS_GROUPS.map((group) => (
          <section key={group.id} className="od-settings-group">
            <h2 className="od-settings-group__title">
              <RailIcon name={group.icon} size={16} /> {group.title}
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
        ))}
      </div>
    </Page>
  )
}
