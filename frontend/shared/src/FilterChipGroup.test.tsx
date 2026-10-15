import { fireEvent, render, screen } from '@testing-library/react'
import { FilterChipGroup } from './FilterChipGroup.js'

const options = [
  { value: 'controls', label: 'Controls' },
  { value: 'icons', label: 'Icons' },
  { value: 'status', label: 'Status', disabled: true },
]

describe('FilterChipGroup', () => {
  it('exposes a named multi-select group and returns the next selected values', () => {
    const onChange = vi.fn()
    render(
      <FilterChipGroup
        label="Catalog filters"
        options={options}
        value={['icons', 'legacy-option']}
        onChange={onChange}
      />,
    )

    expect(screen.getByRole('group', { name: 'Catalog filters' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Icons' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Controls' })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
    expect(screen.getByRole('button', { name: 'Status' })).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: 'Controls' }))
    expect(onChange).toHaveBeenCalledWith(['controls', 'icons', 'legacy-option'])
  })

  it('announces the applied result count and offers a disabled-until-active clear action', () => {
    const onClear = vi.fn()
    const { rerender } = render(
      <FilterChipGroup
        label="Catalog filters"
        options={options}
        value={[]}
        onChange={vi.fn()}
        resultCount={3}
        resultCountLabel={(count) => `${count} matching items`}
        onClear={onClear}
      />,
    )

    expect(screen.getByRole('status')).toHaveTextContent('3 matching items')
    expect(screen.getByRole('button', { name: 'Clear filters' })).toBeDisabled()
    rerender(
      <FilterChipGroup
        label="Catalog filters"
        options={options}
        value={['icons']}
        onChange={vi.fn()}
        resultCount={1}
        onClear={onClear}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(onClear).toHaveBeenCalledOnce()
  })
})
