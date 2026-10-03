import type { ReactNode } from 'react'

/**
 * The one admin page shell: `od-admin-page` with the title and lede. Pages used
 * to hand-roll this div + h1 + paragraph (nine of them still did), which is how
 * they drifted apart. A page-specific class goes in `className`.
 */
export function Page({
  title,
  lede,
  className,
  children,
}: {
  title: ReactNode
  lede?: ReactNode
  className?: string
  children?: ReactNode
}) {
  return (
    <div className={className ? `od-admin-page ${className}` : 'od-admin-page'}>
      <h1>{title}</h1>
      {lede ? <p className="od-admin-lede">{lede}</p> : null}
      {children}
    </div>
  )
}
