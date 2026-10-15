import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

/**
 * Slots in the top bar that page controls render into.
 *
 * Three, not one. The bar answers three different questions and they belong at
 * three different places in it: what can I narrow this to (lead, beside the
 * rail toggle), which sibling view am I on (centre), and how much is here
 * (trail, beside the tile size control). A single slot put all three in a row
 * wherever the widest label happened to leave them.
 */
export const TOPBAR_SLOT_ID = 'od-topbar-slot'
export const TOPBAR_LEAD_ID = 'od-topbar-lead'
export const TOPBAR_TRAIL_ID = 'od-topbar-trail'
/* Four, now. The lead slot sits *inside* the toggle/Filters cluster, so
   anything portalled there is a sibling of the hamburger — correct for
   Filters, wrong for a page title. The title gets its own slot immediately
   after the cluster instead. */
export const TOPBAR_TITLE_ID = 'od-topbar-title'

/** Marks a host div as belonging to one ContextBar instance. */
const HOST_ATTR = 'data-od-contextbar-host'

/**
 * Bar two — everything the current page can do (UIR-1, Option B).
 *
 * Left: a segmented control over sibling views. This is where the page title
 * used to be. Making the name a *switcher* rather than a label is the whole
 * point — a heading that says "Library" when you are already looking at the
 * library is the least useful pixel on the page.
 *
 * Right: one Filters popover and one overflow. Two competing overflow menus is
 * what we are getting away from, so this component deliberately offers exactly
 * one of each.
 *
 * No CSS import: the styles live in the shared `od-appbar.css` theme asset so
 * Jinja admin renders the identical bar (UIR-4) without duplicating anything.
 */

function useDismiss(open: any, onClose: any, refs: any, returnFocusRef: any = null) {
  useEffect(() => {
    if (!open) return undefined

    function onKey(event: any) {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
        returnFocusRef?.current?.focus()
      }
    }
    function onPointer(event: any) {
      // Clicking the trigger toggles; the trigger handles that itself.
      const inside = refs.some((ref: any) => ref.current?.contains(event.target))
      if (!inside) onClose()
    }

    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onPointer)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onPointer)
    }
  }, [open, onClose, refs, returnFocusRef])
}

/**
 * One unified segmented bar. Optional `unfurl` adds a trailing trigger that
 * drops a vertical stack of same-width options attached under that button —
 * only while open. The trigger label is the **active** unfurl option (Tile /
 * Rows / Grid, or News Card / Grid / RSS) so the bar shows which layout you
 * are on; `triggerLabel` is the fallback and the menu's aria-label.
 *
 * @param {object} [props.unfurl]
 * @param {{ id: string, label: string }[]} props.unfurl.views
 * @param {string} props.unfurl.active
 * @param {(id: string) => void} props.unfurl.onSelect
 * @param {string} [props.unfurl.triggerLabel='View'] Fallback + menu name
 */
export function SegmentedViews({
  views,
  active,
  onSelect,
  label = 'Views',
  unfurl = null,
}: LooseProps) {
  const [unfurlOpen, setUnfurlOpen] = useState(false)
  const rootRef = useRef<any>(null)
  const unfurlTriggerRef = useRef<HTMLButtonElement | null>(null)
  const unfurlId = useId()
  const closeUnfurl = useCallback(() => setUnfurlOpen(false), [])
  useDismiss(unfurlOpen, closeUnfurl, [rootRef], unfurlTriggerRef)

  const hasViews = Array.isArray(views) && views.length > 0
  const hasUnfurl = unfurl && Array.isArray(unfurl.views) && unfurl.views.length > 0
  if (!hasViews && !hasUnfurl) return null

  const menuLabel = unfurl?.triggerLabel || 'View'
  const activeUnfurlView = hasUnfurl
    ? unfurl.views.find((view: any) => view.id === unfurl.active)
    : null
  const triggerLabel = activeUnfurlView?.label || menuLabel

  return (
    <div className={`od-contextbar__views${unfurlOpen ? ' is-unfurled' : ''}`} ref={rootRef}>
      <div className={`od-seg${unfurlOpen ? ' is-unfurled' : ''}`} role="group" aria-label={label}>
        {hasViews
          ? views.map((view) => {
              const selected = view.id === active
              return (
                <button
                  key={view.id}
                  type="button"
                  className={`od-seg__item${selected ? ' is-active' : ''}`}
                  aria-pressed={selected}
                  onClick={() => onSelect?.(view.id)}
                >
                  {view.label}
                  {typeof view.count === 'number' ? (
                    <span className="od-seg__count"> {view.count}</span>
                  ) : null}
                </button>
              )
            })
          : null}
        {hasUnfurl ? (
          <span className="od-seg__unfurl-anchor">
            <button
              ref={unfurlTriggerRef}
              type="button"
              className={`od-seg__item${unfurlOpen ? ' is-active' : ''}`}
              aria-expanded={unfurlOpen}
              aria-controls={unfurlOpen ? unfurlId : undefined}
              onClick={() => setUnfurlOpen((value) => !value)}
            >
              {triggerLabel}
            </button>
            {unfurlOpen ? (
              <div
                id={unfurlId}
                className="od-contextbar__views-unfurl"
                role="group"
                aria-label={menuLabel}
              >
                {unfurl.views.map((view: any) => {
                  const selected = view.id === unfurl.active
                  return (
                    <button
                      key={view.id}
                      type="button"
                      className={`od-seg__item${selected ? ' is-active' : ''}`}
                      aria-pressed={selected}
                      onClick={() => {
                        unfurl.onSelect?.(view.id)
                        setUnfurlOpen(false)
                        unfurlTriggerRef.current?.focus()
                      }}
                    >
                      {view.label}
                    </button>
                  )
                })}
              </div>
            ) : null}
          </span>
        ) : null}
      </div>
    </div>
  )
}

/**
 * @param {object} props
 * @param {boolean} [props.chromeless] Drop the panel's own head row. Use when
 *   the content already carries its own frame and dismiss control — otherwise
 *   the panel and the content read as two nested boxes with the trigger's own
 *   label repeated between them.
 * @param {React.ReactNode | ((api: { close: () => void }) => React.ReactNode)}
 *   props.children Given a function, it receives `close` so the content can own
 *   its own dismiss control.
 */
export function Popover({
  label,
  icon = null,
  count = 0,
  children,
  align = 'end',
  chromeless = false,
  /** Extra classes on the trigger — e.g. count readout that opens a panel. */
  triggerClassName = '',
  disabled = false,
  title = undefined,
}: LooseProps) {
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<any>(null)
  const panelRef = useRef<any>(null)
  const panelId = useId()
  const close = useCallback(() => setOpen(false), [])
  const closeAndRestore = useCallback(() => {
    setOpen(false)
    triggerRef.current?.focus()
  }, [])

  useDismiss(open, close, [triggerRef, panelRef], triggerRef)

  const active = count > 0
  const triggerClass = ['od-cbtn', active ? 'is-on' : '', triggerClassName]
    .filter(Boolean)
    .join(' ')

  return (
    <div className="od-pop" data-align={align}>
      <button
        type="button"
        ref={triggerRef}
        className={triggerClass}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-controls={open ? panelId : undefined}
        disabled={disabled}
        title={title}
        onClick={() => setOpen((value) => !value)}
      >
        {icon}
        {label}
        {active ? <span className="od-cbtn__count">{count}</span> : null}
      </button>

      {open ? (
        <div
          id={panelId}
          ref={panelRef}
          className={`od-pop__panel${chromeless ? ' od-pop__panel--bare' : ''}`}
          role="dialog"
          aria-label={label}
        >
          {chromeless ? null : (
            <div className="od-pop__head">
              <span className="od-pop__title">{label}</span>
              <button type="button" className="od-cbtn" onClick={closeAndRestore}>
                Done
              </button>
            </div>
          )}
          {typeof children === 'function' ? children({ close: closeAndRestore }) : children}
        </div>
      ) : null}
    </div>
  )
}

export function ContextBar({
  views,
  activeView,
  onSelectView,
  title = null,
  filters = null,
  filterCount = 0,
  /** Lead-slot popover label. Defaults to Filters. */
  filtersLabel = null,
  /**
   * Open filters from the trail summary ("2 rows") instead of a separate lead
   * button. Discover uses this so the bar does not say Rows twice.
   */
  filtersOnSummary = false,
  summary = null,
  /**
   * Layout / density options that unfurl under a trailing "View" segment on
   * the same bar — not a second always-visible `.od-seg` beside the kinds.
   * Shape matches `SegmentedViews` `unfurl`.
   */
  viewUnfurl = null,
  actions = null,
  overflow = null,
  t = (key: any) => key,
}: LooseProps) {
  const [slots, setSlots] = useState<any>(null)
  const instanceId = useId()

  // Own the nodes we portal into, and evict anyone else's.
  //
  // Portalling straight into the shared slot divs left a page's controls in the
  // bar after that page was gone: the first ContextBar mounted after login
  // never had its portal torn down, so its view strip sat in the centre slot on
  // every subsequent page — Library showed Activity's "Everyone / Friends only"
  // above its own strip, which read as buttons that follow you around. React
  // only removes portal children if the *unmount* runs, and a route that
  // suspends and is discarded can skip it.
  //
  // So each instance appends its own host div, tagged with its id, and sweeps
  // out hosts belonging to any other instance as it arrives. Cleanup still
  // removes our own hosts on the way out; the sweep is what makes a missed
  // cleanup self-correcting rather than permanent — the next page to render
  // controls clears whatever was stranded.
  useLayoutEffect(() => {
    if (typeof document === 'undefined') return undefined

    const centre = document.getElementById(TOPBAR_SLOT_ID)
    if (!centre) return undefined

    const targets = {
      centre,
      lead: document.getElementById(TOPBAR_LEAD_ID),
      title: document.getElementById(TOPBAR_TITLE_ID),
      trail: document.getElementById(TOPBAR_TRAIL_ID),
    }

    const hosts: Record<string, HTMLElement> = {}
    Object.entries(targets).forEach(([name, target]) => {
      if (!target) return
      target.querySelectorAll(`[${HOST_ATTR}]`).forEach((node) => {
        if (node.getAttribute(HOST_ATTR) !== instanceId) node.remove()
      })
      const host = document.createElement('div')
      host.setAttribute(HOST_ATTR, instanceId)
      host.className = 'od-contextbar__host'
      target.appendChild(host)
      hosts[name] = host
    })

    setSlots(hosts)
    return () => {
      Object.values(hosts).forEach((host) => host.remove())
      setSlots(null)
    }
  }, [instanceId])

  // A page that takes `close` owns its own dismiss, so the popover drops its
  // head row: the panel already carries a frame, and the trigger beside it
  // already says "Filters" — with the head the popover drew a second box around
  // a box and repeated the word between them. Pages still passing a plain node
  // (Calendar, Trailers) keep the head, because it holds their only Done.
  const ownsDismiss = typeof filters === 'function'
  const summaryIsFilterTrigger = Boolean(filters && filtersOnSummary && summary)
  const leadLabel = filtersLabel || t('Filters')
  /* Lead Filters (Library): left-anchored so the panel does not open over the
     rail. Trail summary-as-filters (Discover): end-anchored beside tile size. */
  const filterControl =
    filters && !summaryIsFilterTrigger ? (
      <Popover label={leadLabel} count={filterCount} chromeless={ownsDismiss} align="start">
        {filters}
      </Popover>
    ) : null

  const resolvedUnfurl = viewUnfurl
    ? {
        ...viewUnfurl,
        triggerLabel: viewUnfurl.triggerLabel || t('View'),
      }
    : null

  const viewControl = (
    <>
      <SegmentedViews
        views={views}
        active={activeView}
        onSelect={onSelectView}
        label={t('Views')}
        unfurl={resolvedUnfurl}
      />
      {actions}
      {overflow ? <Popover label={t('More')}>{overflow}</Popover> : null}
    </>
  )

  const countControl = summaryIsFilterTrigger ? (
    <Popover
      label={summary}
      count={filterCount}
      chromeless={ownsDismiss}
      align="end"
      triggerClassName="od-contextbar__count"
    >
      {filters}
    </Popover>
  ) : summary ? (
    <span className="od-contextbar__count">{summary}</span>
  ) : null

  /* A name for a page the nav tables cannot name.
   *
   * `getPageTitle` derives bar one's section label from the rail's own link
   * tables, which is right for every routed destination and useless for the
   * ones whose name is data: a Discover row's "see all" page is called
   * whatever that row is called, and the table can only ever say "Discover".
   * DiscoverRowPage had been passing `title` since it was written and this
   * component simply did not accept the prop, so the name was dropped on the
   * floor — the page opened with no indication of which row you had opened.
   *
   * Rendered into the lead slot as the same `.od-topbar__section` element the
   * bar uses for its own titles, so a data-named page reads identically to a
   * table-named one. od-shell.css suppresses the bar's copy when this is
   * present, otherwise a collapsed rail showed both. */
  const titleControl = title ? <h1 className="od-topbar__section">{title}</h1> : null

  // One bar, not two.
  //
  // This rendered as its own row under the top bar, which read as "a toolbar on
  // the page" rather than as chrome — the thing the two-bar layout was supposed
  // to stop. A page's controls belong beside the page's name, so the content
  // portals into the top bar instead.
  //
  // Portalled rather than lifted into TopBar via props: every page already
  // feeds this component, so moving the render target moves all of them at
  // once, and each page keeps owning its own handlers. Same pattern the library
  // filters already use with #od-rail-slot.
  //
  // Three targets rather than one — see the slot ids above. Filters sits with
  // the rail toggle because narrowing is the first thing you do to a list; the
  // views sit centred because they are the page itself; the count sits with the
  // tile size control because both describe how much you are looking at.
  //
  // Falls back to one inline bar when there is no top bar — Big Picture, the
  // pop-out chat host, and tests — rather than vanishing.
  if (!slots) {
    return (
      <div className="od-contextbar">
        {titleControl}
        {viewControl}
        <div className="od-contextbar__actions">
          {countControl}
          {filterControl}
        </div>
      </div>
    )
  }

  // No extra wrapper around `viewControl`: SegmentedViews already renders
  // `.od-contextbar__views`, so wrapping it produced that class nested inside
  // itself and two boxes' worth of layout for one strip.
  return (
    <>
      {createPortal(filterControl, slots.lead || slots.centre)}
      {createPortal(titleControl, slots.title || slots.lead || slots.centre)}
      {createPortal(viewControl, slots.centre)}
      {createPortal(countControl, slots.trail || slots.centre)}
    </>
  )
}
