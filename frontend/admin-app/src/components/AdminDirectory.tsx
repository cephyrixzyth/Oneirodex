import { useState } from 'react'
import { PageStatus } from '@oneirodex/ui'
import { AdminLink } from './AdminLink'
import { buildAdminCommands, filterAdminCommands } from './adminCommands'
import { ADMIN_NAV } from './navConfig'
import { RailIcon } from './railIcons'

const commands = buildAdminCommands()
export function AdminDirectory() {
  const [query, setQuery] = useState('')
  const results = filterAdminCommands(commands, query)
  return (
    <section className="od-directory" aria-labelledby="od-directory-heading">
      <div className="od-directory__header">
        <h2 id="od-directory-heading">Administration</h2>
        <input
          type="search"
          aria-label="Find an admin tool"
          placeholder="Find an admin tool"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>
      {query.trim() ? (
        <>
          <PageStatus announcement="status" inline>
            {results.length} matching {results.length === 1 ? 'tool' : 'tools'}
          </PageStatus>
          <ul className="od-directory__links">
            {results.map((item) => (
              <li key={item.id}>
                <AdminLink to={item.href}>
                  <strong>{item.label}</strong>
                  <small>{item.section}</small>
                </AdminLink>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <ul className="od-directory__sections">
          {ADMIN_NAV.filter((item) => item.id !== 'dashboard').map((item) => (
            <li key={item.id}>
              <AdminLink to={item.path}>
                <RailIcon name={item.id} />
                <strong>{item.label}</strong>
              </AdminLink>
              {commands.some((command) => command.section.split(' · ')[0] === item.label) && (
                <details className="od-directory__group">
                  <summary>Tools in {item.label}</summary>
                  <ul>
                    {commands
                      .filter(
                        (command) =>
                          command.section.split(' · ')[0] === item.label &&
                          command.href !== item.path,
                      )
                      .map((command) => (
                        <li key={command.id}>
                          <AdminLink to={command.href}>{command.label}</AdminLink>
                        </li>
                      ))}
                  </ul>
                </details>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
