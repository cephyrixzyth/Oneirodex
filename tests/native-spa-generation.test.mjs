import assert from 'node:assert/strict'
import {
  existsSync,
  mkdtempSync,
  mkdirSync,
  readFileSync,
  renameSync,
  rmSync,
  writeFileSync,
} from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { test } from 'node:test'
import { promoteGeneration } from '../scripts/native-spa-generation.mjs'

function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'oneirodex-spa-generation-'))
  const current = join(root, 'dist')
  const staged = join(root, 'stage')
  const backup = join(root, 'backup')
  mkdirSync(current)
  mkdirSync(staged)
  writeFileSync(join(current, 'index.html'), 'old generation')
  writeFileSync(join(staged, 'index.html'), 'new generation')
  return { root, current, staged, backup }
}

test('promotes a complete generation and removes its temporary backup', (t) => {
  const state = fixture()
  t.after(() => rmSync(state.root, { recursive: true, force: true }))

  promoteGeneration(state)

  assert.equal(readFileSync(join(state.current, 'index.html'), 'utf8'), 'new generation')
  assert.equal(existsSync(state.backup), false)
})

test('restores the previous generation if staged promotion fails', (t) => {
  const state = fixture()
  t.after(() => rmSync(state.root, { recursive: true, force: true }))
  let failed = false

  assert.throws(
    () =>
      promoteGeneration({
        ...state,
        rename(from, to) {
          if (from === state.staged && !failed) {
            failed = true
            throw new Error('simulated rename failure')
          }
          return renameSync(from, to)
        },
      }),
    /simulated rename failure/,
  )

  assert.equal(readFileSync(join(state.current, 'index.html'), 'utf8'), 'old generation')
  assert.equal(existsSync(state.backup), false)
  assert.equal(existsSync(state.staged), true)
})
