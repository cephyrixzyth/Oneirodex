import { AdminPageActions } from '../components/AdminPageActions'
import { Page } from '../components/Page'
import { SystemResetPanel } from '../components/SystemResetPanel'

/**
 * System → Danger zone.
 *
 * Lives off the Ops glance on purpose: a control that empties database scopes
 * should not sit under the daily observability widgets. Operators reach it from
 * the System rail subsection, after reading the gates on the panel itself.
 */
export function SystemDangerPage() {
  return (
    <Page
      className="od-system-danger"
      title="Danger zone"
      lede="Scoped factory reset for this Oneirodex install. Nothing here deletes game files on disk — only database state you choose. Confirmations are required before anything runs."
    >
      <AdminPageActions label="Danger zone" slot="trail">
        <a className="od-cbtn" href="/admin/ops">
          Back to Ops
        </a>
      </AdminPageActions>

      <SystemResetPanel />
    </Page>
  )
}
