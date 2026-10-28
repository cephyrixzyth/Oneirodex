import type { ReactNode } from 'react'
import type { AccountSummary } from '../accountApi.js'
import { PageStatus } from '../pageStatus.js'
import { avatarSrc } from './accountModalShared'

/* Note + ProfilePanel moved out of AccountModal (v11 cycle, H-D.2) — unchanged. */

export interface NoteProps {
  tone: 'error' | 'good' | 'warning'
  children?: ReactNode
}

export function Note({ tone, children }: NoteProps): ReactNode {
  if (!children) return null
  return (
    <p
      className={`od-acct__note od-acct__note--${tone}`}
      role={tone === 'error' ? 'alert' : 'status'}
    >
      {children}
    </p>
  )
}

/* ---------------------------------------------------------------- profile */

/**
 * Who you are, and nothing else.
 *
 * It used to carry a row apiece for Invites, Avatar and Password, each with a
 * button that switched to the tab sitting directly above it. Three rows to say
 * what three tabs already said, and the "3 of 5 invites left" line repeated
 * what the Invites panel opens with.
 */
export function ProfilePanel({ summary }: { summary: AccountSummary | null }): ReactNode {
  if (!summary) return <PageStatus loading inline className="od-acct__empty" />

  return (
    <div className="od-acct__avatar-row">
      <img className="od-acct__avatar" src={avatarSrc(summary, summary.avatar_path)} alt="" />
      <div className="od-acct__avatar-meta">
        <p className="od-acct__row-title">{summary.username}</p>
        <p className="od-acct__row-sub">{summary.role}</p>
        {/* An emailless household account shows what it is rather than a
            placeholder address nobody can write to. */}
        <p className="od-acct__row-sub">{summary.email || 'No email on this account'}</p>
      </div>
    </div>
  )
}

/* ----------------------------------------------------------------- avatar */
