import { describe, expect, it } from 'vitest'
import { adminLoginUrl } from './adminApi'

describe('adminLoginUrl', () => {
  it('preserves the current admin route and query for the post-login return', () => {
    expect(
      adminLoginUrl('/admin/library/edit/lib-1', '?mode=edit', '#image'),
    ).toBe('/login?next=%2Fadmin%2Flibrary%2Fedit%2Flib-1%3Fmode%3Dedit%23image')
  })
})
