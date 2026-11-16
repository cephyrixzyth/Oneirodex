import { InvitesPanel } from '@oneirodex/ui'
import { Link } from 'react-router-dom'
import './InvitesPage.css'

const LINKS = [
  { label: 'Profile', to: '/settings_profile_view' },
  { label: 'Password', to: '/settings_password' },
  { label: 'Invites', to: '/user/invites', current: true },
  { label: 'Library', to: '/library' },
]

export function InvitesPage() {
  return (
    <div className="od-more-page od-invites-page">
      <nav className="od-invites-page__nav" aria-label="Account settings">
        {LINKS.map((link) => (
          <Link
            key={link.to}
            to={link.to}
            aria-current={link.current ? 'page' : undefined}
            className={link.current ? 'is-current' : undefined}
          >
            {link.label}
          </Link>
        ))}
        <Link to="/library?account=avatar">Avatar</Link>
        <Link to="/tokens">API tokens</Link>
      </nav>

      <h2 className="od-invites-page__title">Invites</h2>
      <p className="od-more-page__lede">
        Invite friends to your household library. Unused invites return after 48 hours.
      </p>
      <div className="od-invites-page__content">
        <InvitesPanel />
      </div>
    </div>
  )
}
