import { describe, expect, test } from 'vitest'
import { DASHBOARD_COLS } from './dashboardLayout'
import { OPS_METRIC_IDS, defaultOpsLayout, opsWidgetMins } from './opsLayout'

describe('defaultOpsLayout', () => {
  test('metrics fill each row without leftover columns', () => {
    const layout = defaultOpsLayout()
    const metrics = layout.filter((item) => item.id.startsWith('m-'))
    expect(metrics).toHaveLength(OPS_METRIC_IDS.length)
    const rows = new Map()
    metrics.forEach((item) => {
      const list = rows.get(item.y) || []
      list.push(item)
      rows.set(item.y, list)
    })
    for (const row of rows.values()) {
      const width = row.reduce((sum: any, item: any) => sum + item.w, 0)
      expect(width).toBe(DASHBOARD_COLS)
    }
  })

  test('visibleIds drops absent detail panels', () => {
    const layout = defaultOpsLayout({
      visibleIds: ['status', 'm-cpu', 'host', 'scans'],
    })
    const ids = layout.map((item) => item.id)
    expect(ids).toEqual(['status', 'm-cpu', 'host', 'scans'])
  })
})

test('opsWidgetMins keeps status compact and wide panels above metric floor', () => {
  expect(opsWidgetMins('status').h).toBe(1)
  expect(opsWidgetMins('m-cpu')).toEqual({ w: 2, h: 2 })
  expect(opsWidgetMins('recent-log').w).toBeGreaterThanOrEqual(4)
  expect(opsWidgetMins('detail-system').w).toBeGreaterThanOrEqual(3)
})
