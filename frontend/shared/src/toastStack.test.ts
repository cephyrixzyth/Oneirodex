import { describe, expect, it } from 'vitest'

import {
  MAX_INDIVIDUAL_TOASTS,
  MAX_NARROW_INDIVIDUAL_TOASTS,
  planToastStack,
  stackSummaryMessage,
} from './toastStack.js'

describe('planToastStack', () => {
  it('lets three individual toasts through', () => {
    expect(planToastStack({ stackedCount: 2, incomingCount: 1 })).toEqual({ action: 'append' })
    expect(MAX_INDIVIDUAL_TOASTS).toBe(3)
  })

  it('collapses when the fourth would appear', () => {
    expect(planToastStack({ stackedCount: 3, incomingCount: 1 })).toEqual({
      action: 'collapse',
      nextCount: 4,
    })
  })

  it('supports a narrower viewport cap', () => {
    expect(
      planToastStack({
        stackedCount: 2,
        incomingCount: 1,
        maxIndividual: MAX_NARROW_INDIVIDUAL_TOASTS,
      }),
    ).toEqual({
      action: 'collapse',
      nextCount: 3,
    })
    expect(MAX_NARROW_INDIVIDUAL_TOASTS).toBe(2)
  })

  it('collapses a burst already over the cap', () => {
    expect(planToastStack({ stackedCount: 0, incomingCount: 12 })).toEqual({
      action: 'collapse',
      nextCount: 12,
    })
  })

  it('increments an existing summary instead of stacking beside it', () => {
    expect(planToastStack({ stackedCount: 4, hasSummary: true, incomingCount: 3 })).toEqual({
      action: 'increment-summary',
      add: 3,
    })
  })
})

describe('stackSummaryMessage', () => {
  it('names the count', () => {
    expect(stackSummaryMessage(6)).toBe('6 notifications')
    expect(stackSummaryMessage(1)).toBe('1 notification')
  })
})
