import type * as THREE from 'three'
import type { RoomView } from './roomScene'
import { READING_DISPLAY as R } from './roomLayout'

type Sign = (
  w: number,
  h: number,
  x: number,
  y: number,
  z: number,
  angle: number,
  title: string,
  copy: string,
  action?: string,
) => void
type Plane = (
  w: number,
  h: number,
  x: number,
  y: number,
  z: number,
  angle: number,
  texture: THREE.Texture,
) => void

/** Screens and control plaques live on the authored desk/window assemblies. */
export function drawObservatoryStations(
  sign: Sign,
  plane: Plane,
  texture: THREE.Texture,
  view: RoomView,
  page: number,
  pages: number,
) {
  plane(R.width, R.height, R.x, R.y, R.z, Math.PI / 2, texture)
  sign(0.7, 0.14, R.x, R.toolbarY, -1.4, Math.PI / 2, 'Library wall', '', '@library')
  if (view.selected)
    sign(
      0.7,
      0.14,
      R.x,
      R.toolbarY,
      -0.5,
      Math.PI / 2,
      view.selected.is_favorite ? 'Remove favorite' : 'Add favorite',
      '',
      '@favorite',
    )
  sign(0.7, 0.14, R.x, R.topY, -1.4, Math.PI / 2, 'Recenter', '', '@home')
  sign(
    0.7,
    0.14,
    R.x,
    R.topY,
    -0.5,
    Math.PI / 2,
    'Text size',
    view.largeText ? 'Large' : 'Standard',
    '@text',
  )
  if (pages > 1) {
    if (page > 0) sign(0.3, 0.14, R.x, R.toolbarY, -1.96, Math.PI / 2, 'Previous', '', '@read-back')
    if (page + 1 < pages)
      sign(0.3, 0.14, R.x, R.toolbarY, 0.06, Math.PI / 2, 'Next', '', '@read-next')
  }
  for (const [y, title, copy, action] of [
    [2.1, 'Recenter', 'Reset view', '@home'],
    [1.78, 'Comfort', view.comfort || 'Standard', '@comfort'],
    [1.46, 'Library wall', 'Return', '@library'],
    [1.14, 'Favorite shelf', 'Your titles', '@favorites'],
  ] as const)
    sign(0.85, 0.2, 4.7, y, -0.8, -Math.PI / 2, title, copy, action)
}
