import { Link } from 'react-router-dom'
import { Page } from '../components/Page'

const ADMIN_HELP_LINKS = [
  {
    title: 'Dashboard and system health',
    description: 'Read server status, recent activity, storage and service signals.',
    href: '/admin/dashboard',
  },
  {
    title: 'Libraries and scans',
    description: 'Manage libraries, start scans, review jobs and resolve unmatched folders.',
    href: '/libraries',
  },
  {
    title: 'Users and access',
    description: 'Manage accounts, invites, allowlists and administrator access.',
    href: '/admin/users',
  },
  {
    title: 'Themes and appearance',
    description: 'Manage installed themes, icon packs and theme files.',
    href: '/admin/themes',
  },
  {
    title: 'Integrations',
    description: 'Configure metadata providers, email, identity and connected services.',
    href: '/admin/integrations',
  },
  {
    title: 'Operations and troubleshooting',
    description: 'Inspect logs, service health and common recovery steps.',
    href: '/admin/ops',
  },
]

export function AdminHelpPage() {
  return (
    <Page
      title="Admin help"
      lede="Quick paths for the common setup, library, access and operations tasks."
    >
      <div className="od-admin-panel">
        <ul className="od-settings-list">
          {ADMIN_HELP_LINKS.map((item) => (
            <li key={item.href}>
              <Link className="od-settings-row" to={item.href}>
                <span className="od-settings-row__title">{item.title}</span>
                <span className="od-admin-lede">{item.description}</span>
              </Link>
            </li>
          ))}
        </ul>
        <p className="od-admin-lede">
          For account, playback and collection questions, open the{' '}
          <a href="/help">member help guide</a>.
        </p>
      </div>
    </Page>
  )
}
