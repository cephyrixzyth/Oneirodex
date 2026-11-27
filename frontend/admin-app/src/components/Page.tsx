import { useEffect, useRef, type ReactNode } from 'react'

import { AdminPageActions } from './AdminPageActions'

export function useAdminDocumentTitle(pageTitle: string) {
  useEffect(() => {
    const previousTitle = document.title
    document.title = `${pageTitle} · Oneirodex Admin`
    return () => {
      document.title = previousTitle
    }
  }, [pageTitle])
}

/**
 * The one admin page shell: `od-admin-page` with the title and lede. Pages used
 * to hand-roll this div + h1 + paragraph (nine of them still did), which is how
 * they drifted apart. A page-specific class goes in `className`.
 */
export function Page({
  title,
  documentTitle,
  lede,
  actions,
  className,
  children,
}: {
  title: ReactNode
  documentTitle?: string
  /** Kept for callers; every page title is now visually hidden in favour of the top bar. */
  visuallyHiddenTitle?: boolean
  lede?: ReactNode
  actions?: ReactNode
  className?: string
  children?: ReactNode
}) {
  const headingRef = useRef<HTMLHeadingElement>(null)

  useEffect(() => {
    const previousTitle = document.title
    const heading = documentTitle?.trim() || headingRef.current?.textContent?.trim()
    if (heading) document.title = `${heading} · Oneirodex Admin`
    return () => {
      document.title = previousTitle
    }
  }, [title, documentTitle])

  return (
    <div className={className ? `od-admin-page ${className}` : 'od-admin-page'}>
      {/* The page's visible name lives in the top bar: the active section tab
          when the bar has one, otherwise this title beside the rail toggle.
          The in-page h1 stays for assistive technology and the document title
          but is not drawn a second time as a large heading. */}
      <AdminPageActions slot="title" label="Page title">
        <span className="od-topbar__page-title">{title}</span>
      </AdminPageActions>
      <header className="od-admin-page__heading">
        <div>
          <h1 ref={headingRef} className="visually-hidden">
            {title}
          </h1>
          {lede ? <p className="od-admin-lede">{lede}</p> : null}
        </div>
        {actions ? <div className="od-admin-page__actions">{actions}</div> : null}
      </header>
      {children}
    </div>
  )
}
