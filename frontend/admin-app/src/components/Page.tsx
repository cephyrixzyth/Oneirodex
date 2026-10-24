import { useEffect, useRef, type ReactNode } from 'react'

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
  className,
  children,
}: {
  title: ReactNode
  documentTitle?: string
  lede?: ReactNode
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
      <h1 ref={headingRef}>{title}</h1>
      {lede ? <p className="od-admin-lede">{lede}</p> : null}
      {children}
    </div>
  )
}
