import type { ReactNode } from 'react'

import { Link } from 'react-router-dom'
import { Page } from './Page'

interface HubLink {
  href: string
  label: string
}

/**
 * A section landing page with no body of its own (GT-B35).
 *
 * The copy here used to read: "This admin surface runs in the React shell. Use
 * the actions above for the full workflow. Form POSTs still hit the existing
 * Flask endpoints." Two problems, one of them a dead end.
 *
 * There are no actions above. GT-B7 deleted the per-page `LinkRow` when the
 * rail took over destinations, so the sentence pointed at controls that had
 * been removed — and this is precisely the page with nothing else on it, so an
 * operator following that instruction found blank space. The second sentence
 * described the app's internal wiring, which is not something an operator can
 * act on and not something they should have to read.
 *
 * `links` is how it stops being a dead end. Passing a section's destinations is
 * *not* the LinkRow mistake returning: LinkRow put a duplicate nav on top of
 * every page that already had content. Here the list is the entire purpose of
 * the page, and it is also the only route to those destinations when the rail
 * is a closed drawer on a narrow screen.
 */
export function HubPage({
  title,
  lede,
  links = [],
}: {
  title: ReactNode
  lede?: ReactNode
  links?: HubLink[]
}) {
  return (
    <Page title={title} lede={lede}>
      <div className="od-admin-panel">
        {links.length ? (
          <ul className="od-settings-list">
            {links.map((link) => (
              <li key={link.href}>
                <Link className="od-settings-row" to={link.href}>
                  <span className="od-settings-row__title">{link.label}</span>
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="od-admin-lede">
            Pick a destination for this section from the rail on the left.
          </p>
        )}
      </div>
    </Page>
  )
}
