/**
 * Cap the live toast stack so a scan burst cannot cover the page.
 *
 * Three info/success toasts stay individual on desktop. Narrow layouts keep at
 * most two individual toasts so a scan burst cannot cover the active controls.
 * Larger bursts collapse to one “N notifications” line. Errors and warnings
 * never join that stack — they still need their own sentence.
 */

export const MAX_INDIVIDUAL_TOASTS = 3
export const MAX_NARROW_INDIVIDUAL_TOASTS = 2

export type ToastTone = 'info' | 'success' | 'error' | 'warn'

export interface ToastStackState {
  stackedCount?: number
  hasSummary?: boolean
  incomingCount?: number
  maxIndividual?: number
}

export type ToastStackPlan =
  | { action: 'append' }
  | { action: 'increment-summary'; add: number }
  | { action: 'collapse'; nextCount: number }

export function stackSummaryMessage(count: number): string {
  const n = Math.max(0, Math.floor(Number(count) || 0))
  return `${n} notification${n === 1 ? '' : 's'}`
}

export function isStackableTone(tone: string): boolean {
  return tone === 'info' || tone === 'success'
}

export function planToastStack({
  stackedCount = 0,
  hasSummary = false,
  incomingCount = 1,
  maxIndividual = MAX_INDIVIDUAL_TOASTS,
}: ToastStackState = {}): ToastStackPlan {
  const incoming = incomingCount > 0 ? incomingCount : 1
  const current = stackedCount > 0 ? stackedCount : 0
  const cap =
    Number.isInteger(maxIndividual) && maxIndividual > 0 ? maxIndividual : MAX_INDIVIDUAL_TOASTS
  if (hasSummary) {
    return { action: 'increment-summary', add: incoming }
  }
  if (current + incoming > cap) {
    return { action: 'collapse', nextCount: current + incoming }
  }
  return { action: 'append' }
}
