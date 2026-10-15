import { Button } from './Button.js'
import type { ReactNode } from 'react'

export interface FilterChipOption {
  value: string
  label: ReactNode
  title?: string
  disabled?: boolean
}

export interface FilterChipGroupProps {
  /** Accessible name for this set of independent, multi-select filters. */
  label: string
  options: readonly FilterChipOption[]
  /** The selection the owning feature considers current. */
  value: readonly string[]
  onChange: (next: string[]) => void
  /** Pass the result count for the applied selection, never an unapplied draft. */
  resultCount?: number
  resultCountLabel?: (count: number) => ReactNode
  onClear?: () => void
  clearLabel?: string
  size?: 'compact' | 'comfortable'
  className?: string
}

/**
 * Shared, controlled multi-select filter chips.
 *
 * The owner controls whether changes apply immediately or remain a draft, and
 * supplies only an applied result count. Option meaning and query serialization
 * stay with the owning feature. Selected values absent from a temporarily
 * unavailable option list are preserved until the owner clears them.
 */
export function FilterChipGroup({
  label,
  options,
  value,
  onChange,
  resultCount,
  resultCountLabel = (count) => `${count} results`,
  onClear,
  clearLabel = 'Clear filters',
  size = 'comfortable',
  className = '',
}: FilterChipGroupProps) {
  const selected = new Set(value)
  const classes = [
    'od-filter-chip-group',
    size === 'compact' ? 'od-filter-chip-group--compact' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ')

  const toggle = (optionValue: string) => {
    const optionValues = new Set(options.map((option) => option.value))
    const next = new Set(value.filter((selectedValue) => !optionValues.has(selectedValue)))
    for (const selectedValue of value) {
      if (optionValues.has(selectedValue)) next.add(selectedValue)
    }
    if (next.has(optionValue)) next.delete(optionValue)
    else next.add(optionValue)
    onChange([
      ...options.filter((option) => next.has(option.value)).map((option) => option.value),
      ...value.filter((selectedValue) => !optionValues.has(selectedValue)),
    ])
  }

  return (
    <div className={classes}>
      <div className="od-filter-chip-group__options" role="group" aria-label={label}>
        {options.map((option) => {
          const active = selected.has(option.value)
          return (
            <button
              key={option.value}
              type="button"
              className="od-filter-chip"
              aria-pressed={active}
              title={option.title}
              disabled={option.disabled}
              onClick={() => toggle(option.value)}
            >
              {option.label}
            </button>
          )
        })}
      </div>
      {resultCount !== undefined || onClear ? (
        <div className="od-filter-chip-group__meta">
          {resultCount !== undefined ? (
            <span className="od-filter-chip-group__count" role="status" aria-live="polite">
              {resultCountLabel(resultCount)}
            </span>
          ) : null}
          {onClear ? (
            <Button variant="quiet" size="sm" disabled={value.length === 0} onClick={onClear}>
              {clearLabel}
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

export default FilterChipGroup
