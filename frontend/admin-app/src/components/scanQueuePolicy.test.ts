import { describe, expect, test } from 'vitest'
import {
  SCAN_CONFLICT_COPY,
  SCAN_QUEUE_POLICY,
  buildScanQueueRequestFields,
  hasActiveScan,
  isAlreadyRunningReject,
  isScanBusyStatus,
  isScanRunning,
  isScanQueuedStatus,
  normalizeScanJobsList,
  isScanCoalesced,
  toastForScanStartResponse,
  toastToneForScanVariant,
} from './scanQueuePolicy'

describe('scanQueuePolicy', () => {
  test('buildScanQueueRequestFields defaults queue and maps force', () => {
    // Shared by Auto Scan, Manual busy (Jinja intercept), Refresh all, restart-while-busy.
    expect(buildScanQueueRequestFields()).toEqual({
      queue_policy: 'queue',
      force_parallel: false,
    })
    expect(buildScanQueueRequestFields(SCAN_QUEUE_POLICY.QUEUE)).toEqual({
      queue_policy: 'queue',
      force_parallel: false,
    })
    expect(buildScanQueueRequestFields(SCAN_QUEUE_POLICY.FORCE)).toEqual({
      queue_policy: 'force',
      force_parallel: true,
    })
    expect(buildScanQueueRequestFields('unknown')).toEqual({
      queue_policy: 'queue',
      force_parallel: false,
    })
  })

  test('Manual busy and Auto Scan share the same conflict field map', () => {
    // Smoke: classic Manual busy posts these via applyQueueFieldsToForm; idle Manual omits them.
    const queue = buildScanQueueRequestFields(SCAN_QUEUE_POLICY.QUEUE)
    const force = buildScanQueueRequestFields(SCAN_QUEUE_POLICY.FORCE)
    expect(Object.keys(queue).sort()).toEqual(['force_parallel', 'queue_policy'])
    expect(queue).toEqual({ queue_policy: 'queue', force_parallel: false })
    expect(force).toEqual({ queue_policy: 'force', force_parallel: true })
    expect(SCAN_CONFLICT_COPY.queueLabel).toMatch(/Queue/i)
    expect(SCAN_CONFLICT_COPY.forceLabel).toMatch(/Force/i)
  })

  test('busy and queued status helpers', () => {
    expect(isScanBusyStatus('Running')).toBe(true)
    expect(isScanBusyStatus('Stopping')).toBe(true)
    expect(isScanBusyStatus('Queued')).toBe(false)
    expect(isScanQueuedStatus('Queued')).toBe(true)
    expect(isScanQueuedStatus('pending')).toBe(true)
    expect(isScanQueuedStatus('scheduled')).toBe(true)
    expect(isScanQueuedStatus('Running')).toBe(false)
  })

  test('hasActiveScan reads array or jobs payload', () => {
    expect(hasActiveScan([{ status: 'Completed' }, { status: 'Running' }])).toBe(true)
    expect(hasActiveScan({ jobs: [{ status: 'Queued' }] })).toBe(false)
    expect(normalizeScanJobsList({ jobs: [{ id: '1' }] })).toHaveLength(1)
  })

  test('isAlreadyRunningReject covers 409 and rejected copy', () => {
    expect(isAlreadyRunningReject(409, { error: 'A scan is already running' })).toBe(true)
    expect(
      isAlreadyRunningReject(200, {
        status: 'rejected',
        message: 'A scan is already in progress',
      }),
    ).toBe(true)
    expect(isAlreadyRunningReject(200, { status: 'queued' })).toBe(false)
  })

  test('toastForScanStartResponse maps queued|started|rejected', () => {
    expect(toastForScanStartResponse({ status: 'queued', position: 2 }).variant).toBe('info')
    expect(toastForScanStartResponse({ status: 'queued', position: 2 }).text).toBe(
      'Queued · position 2',
    )
    expect(
      toastForScanStartResponse({
        status: 'queued',
        jobs: [{ position: 3 }],
        message: 'long backend copy',
      }).text,
    ).toBe('Queued · position 3')
    expect(
      toastForScanStartResponse({
        status: 'queued',
        position: 1,
        coalesced: true,
      }).text,
    ).toBe('Queued · position 1 · coalesced')
    expect(
      toastForScanStartResponse({
        status: 'queued',
        position: 2,
        jobs: [{ position: 2, coalesced: true }],
      }).text,
    ).toBe('Queued · position 2 · coalesced')
    expect(isScanCoalesced({ coalesced_count: 1 })).toBe(true)
    expect(toastForScanStartResponse({ status: 'started' }).variant).toBe('success')
    expect(
      toastForScanStartResponse({ status: 'started', message: 'Scan started.', risk: 'NAS risk' })
        .variant,
    ).toBe('warning')
    expect(
      toastForScanStartResponse({ status: 'started', message: 'Scan started.', risk: 'NAS risk' })
        .text,
    ).toMatch(/NAS risk/)
    expect(
      toastForScanStartResponse({
        status: 'started',
        message: 'Scan started in parallel. NAS risk',
        risk: 'NAS risk',
      }),
    ).toEqual({ text: 'Scan started in parallel. NAS risk', variant: 'warning' })
    expect(toastForScanStartResponse({ status: 'rejected', error: 'Nope' }, false).text).toBe(
      'Nope',
    )
    expect(toastForScanStartResponse({ count: 3 }, true).text).toMatch(/Queued · 3/)
    expect(toastToneForScanVariant('warning')).toBe('warn')
    expect(toastToneForScanVariant('info')).toBe('info')
  })

  test('conflict copy stays honest about Unraid/NAS load', () => {
    expect(SCAN_CONFLICT_COPY.forceWarning).toMatch(/Unraid\/NAS/)
    expect(SCAN_CONFLICT_COPY.queueHint).toMatch(/safer/)
  })
})

describe('isScanRunning (GT-B13)', () => {
  test('is false on an install that has never scanned', () => {
    // The reported bug: "Scanning…" on a fresh install with no libraries.
    expect(isScanRunning({ jobs: [], running: true })).toBe(false)
    expect(isScanRunning({ jobs: [] })).toBe(false)
    expect(isScanRunning([])).toBe(false)
    expect(isScanRunning(null)).toBe(false)
  })

  test('trusts a busy job on its own', () => {
    expect(isScanRunning({ jobs: [{ status: 'Running' }] })).toBe(true)
    expect(isScanRunning([{ status: 'Stopping' }])).toBe(true)
  })

  test('accepts the payload flag once a job corroborates it', () => {
    expect(isScanRunning({ jobs: [{ status: 'Completed' }], running: true })).toBe(true)
  })

  test('matches busy status regardless of case', () => {
    // isScanQueuedStatus lowercased and this did not, so the two disagreed
    // about the same payload.
    expect(isScanBusyStatus('running')).toBe(true)
    expect(isScanBusyStatus('RUNNING')).toBe(true)
    expect(isScanBusyStatus('Running')).toBe(true)
    expect(isScanBusyStatus('completed')).toBe(false)
  })
})
