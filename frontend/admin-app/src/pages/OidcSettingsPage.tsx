import { Page } from '../components/Page'
import { OidcSettingsPanel } from './OidcSettingsPanel'

export function OidcSettingsPage() {
  return (
    <Page title="OIDC / SSO" lede="Optional single sign-on configuration and local readiness.">
      <OidcSettingsPanel />
    </Page>
  )
}
