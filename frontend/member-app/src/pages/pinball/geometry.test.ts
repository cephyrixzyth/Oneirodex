import * as THREE from 'three'
import { describe, expect, it, vi } from 'vitest'
import { roomArtSlug } from '../roomWorlds'
import { furnishObservatory } from '../roomObservatory'
import { createPinballTable, boardPosition } from './render'
import { newMoonfall, stepMoonfall } from './model'
import { RAILS, TARGETS } from './table'

describe('original observatory and table geometry (no WebGL renderer)', () => {
  it('keeps baked table grounding above the rug when dynamic shadows are disabled', () => {
    const scene = new THREE.Scene()
    const room = furnishObservatory(scene)
    const table = createPinballTable()
    scene.add(table.group)
    scene.updateMatrixWorld(true)
    const rug = scene.getObjectByName('observatory-rug')!
    const shadow = scene.getObjectByName('pinball-ground-contact')!
    const ray = new THREE.Raycaster(new THREE.Vector3(0, 0.2, 0), new THREE.Vector3(0, -1, 0))
    const hits = ray.intersectObjects([rug, shadow], false)
    expect(hits[0].object).toBe(shadow)
    table.dispose()
    room.dispose()
  })
  it('gives the default theme its own identity', () => {
    expect(roomArtSlug('default')).toBe('oneirodex')
    expect(roomArtSlug('oneirodex')).toBe('oneirodex')
    expect(roomArtSlug('greenhouse')).toBe('greenhouse')
  })

  it('authors the dome, panorama, library and instruments as actual scene objects', () => {
    const scene = new THREE.Scene()
    const room = furnishObservatory(scene)
    for (const name of [
      'observatory-dome',
      'observatory-aurora',
      'observatory-library',
      'observatory-telescope',
      'observatory-orrery',
      'observatory-seating',
    ]) {
      expect(scene.getObjectByName(name), name).toBeDefined()
    }
    let meshes = 0
    scene.traverse((object) => {
      if (object instanceof THREE.Mesh) meshes++
    })
    expect(meshes).toBeGreaterThan(25)
    expect(meshes).toBeLessThan(260)
    expect(room.canStandAt(0, 2.5)).toBe(true)
    expect(room.canStandAt(0, 0)).toBe(false)
    expect(room.canStandAt(9, 0)).toBe(false)
    room.dispose()
  })

  it('detaches and disposes owned geometry once, even after repeated cleanup', () => {
    const scene = new THREE.Scene()
    const room = furnishObservatory(scene)
    const dome = scene.getObjectByName('observatory-dome') as THREE.Mesh
    const dispose = vi.spyOn(dome.geometry, 'dispose')
    room.dispose()
    room.dispose()
    expect(dispose).toHaveBeenCalledOnce()
    expect(scene.getObjectByName('observatory-dome')).toBeUndefined()
  })

  it('aligns visible rails and targets to the same layout used by physics', () => {
    const table = createPinballTable()
    RAILS.forEach((rail, i) => {
      const visible = table.group.getObjectByName('pinball-rail-' + i)!
      const middle = boardPosition((rail.ax + rail.bx) / 2, (rail.ay + rail.by) / 2)
      expect(visible.position.x).toBeCloseTo(middle.x)
      expect(visible.position.z).toBeCloseTo(middle.z)
    })
    for (const target of TARGETS)
      expect(table.group.getObjectByName('pinball-target-' + target.id)).toBeDefined()
    table.dispose()
  })

  it('renders the real model ball and flipper state rather than a decorative animation', () => {
    const table = createPinballTable()
    const state = newMoonfall(42)
    stepMoonfall(state, { left: true, right: false, launch: true, recover: false }, 1 / 120)
    table.update(state)
    const ball = table.group.getObjectByName('pinball-ball-slot-0')!
    const expected = boardPosition(state.balls[0].x, state.balls[0].y)
    expect(ball.visible).toBe(true)
    expect(ball.position.x).toBeCloseTo(expected.x)
    expect(ball.position.z).toBeCloseTo(expected.z)
    expect(table.group.getObjectByName('pinball-flipper-left')!.rotation.y).toBeCloseTo(
      -state.flippers.left,
    )
    table.dispose()
  })
})

it('renders elevated crescent ramps and moving identifiable target symbols', () => {
  const table = createPinballTable()
  const state = newMoonfall()
  expect(table.group.getObjectByName('pinball-ramp-left')).toBeDefined()
  expect(table.group.getObjectByName('pinball-ramp-right')).toBeDefined()
  for (const id of ['orbit', 'moon', 'aurora'])
    expect(table.group.getObjectByName('pinball-symbol-' + id)).toBeDefined()
  table.update(state)
  const target = table.group.getObjectByName('pinball-target-orbit')!
  const before = target.position.clone()
  state.tick = 120
  table.update(state)
  expect(target.position.equals(before)).toBe(false)
  table.dispose()
})

it('lets the reader adjust instruments without moving the camera or needing animation', () => {
  const room = furnishObservatory(new THREE.Scene())
  const telescope = room.group.getObjectByName('telescope-head')!
  const orrery = room.group.getObjectByName('observatory-orrery')!
  const before = telescope?.rotation.y
  room.interact('telescope')
  expect(telescope.rotation.y).not.toBe(before)
  room.update(10, true)
  room.interact('orrery')
  const angle = orrery.rotation.y
  room.update(20, true)
  expect(orrery.rotation.y).toBe(angle)
  expect(room.actionMeshes.length).toBeGreaterThan(0)
  room.dispose()
})
