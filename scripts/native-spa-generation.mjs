import { renameSync, rmSync, statSync } from 'node:fs'

export function promoteGeneration({
  current,
  staged,
  backup,
  exists = (path) => Boolean(statSync(path, { throwIfNoEntry: false })),
  rename = renameSync,
  remove = rmSync,
  warn = console.warn,
}) {
  const hadCurrent = exists(current)
  let backedUp = false
  try {
    if (hadCurrent) {
      rename(current, backup)
      backedUp = true
    }
    rename(staged, current)
  } catch (error) {
    if (backedUp && !exists(current) && exists(backup)) {
      try {
        rename(backup, current)
      } catch (restoreError) {
        throw new AggregateError(
          [error, restoreError],
          `SPA promotion failed and the previous generation remains at ${backup}`,
        )
      }
    }
    throw error
  }

  if (backedUp) {
    try {
      remove(backup, { recursive: true, force: true })
    } catch (error) {
      warn(
        `New SPA generation is active; previous generation remains at ${backup}: ${error.message}`,
      )
    }
  }
}
