import type { ArtStudioTab } from './artStudioModel'
import type { KeyboardEvent } from 'react'

/** The studio / stock / marks / images tab strip. */
export function ArtStudioTabs({
  selectTab,
  tab,
}: {
  selectTab: (next: ArtStudioTab) => void
  tab: ArtStudioTab
}) {
  const tabs: ArtStudioTab[] = ['studio', 'stock', 'marks', 'images']
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const current = tabs.indexOf(tab)
    let next = -1
    if (event.key === 'ArrowRight') next = (current + 1) % tabs.length
    if (event.key === 'ArrowLeft') next = (current - 1 + tabs.length) % tabs.length
    if (event.key === 'Home') next = 0
    if (event.key === 'End') next = tabs.length - 1
    if (next < 0) return
    event.preventDefault()
    selectTab(tabs[next])
    event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next]?.focus()
  }
  return (
    <div
      className="od-art-tabs"
      role="tablist"
      aria-label="Art studio sections"
      onKeyDown={onKeyDown}
    >
      <button
        type="button"
        role="tab"
        id="art-tab-studio"
        aria-controls="art-panel-studio"
        tabIndex={tab === 'studio' ? 0 : -1}
        aria-selected={tab === 'studio'}
        className={`od-art-tabs__btn${tab === 'studio' ? ' is-active' : ''}`}
        onClick={() => selectTab('studio')}
      >
        Studio
      </button>
      <button
        type="button"
        role="tab"
        id="art-tab-stock"
        aria-controls="art-panel-stock"
        tabIndex={tab === 'stock' ? 0 : -1}
        aria-selected={tab === 'stock'}
        className={`od-art-tabs__btn${tab === 'stock' ? ' is-active' : ''}`}
        onClick={() => selectTab('stock')}
      >
        Backup &amp; stock
      </button>
      <button
        type="button"
        role="tab"
        id="art-tab-marks"
        aria-controls="art-panel-marks"
        tabIndex={tab === 'marks' ? 0 : -1}
        aria-selected={tab === 'marks'}
        className={`od-art-tabs__btn${tab === 'marks' ? ' is-active' : ''}`}
        onClick={() => selectTab('marks')}
      >
        System marks
      </button>
      <button
        type="button"
        role="tab"
        id="art-tab-images"
        aria-controls="art-panel-images"
        tabIndex={tab === 'images' ? 0 : -1}
        aria-selected={tab === 'images'}
        className={`od-art-tabs__btn${tab === 'images' ? ' is-active' : ''}`}
        onClick={() => selectTab('images')}
      >
        Pick &amp; queue
      </button>
    </div>
  )
}
