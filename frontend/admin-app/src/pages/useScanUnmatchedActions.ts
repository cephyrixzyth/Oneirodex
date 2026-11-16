import { csrfHeaders, getJson, postJson } from '../api/adminApi'
import { type UnmatchedRow, entryLabel } from './scanUnmatchedTypes'
import type { useScanUnmatchedData } from './useScanUnmatchedData'
export function useScanUnmatchedActions(data: ReturnType<typeof useScanUnmatchedData>) {
  const {
    setLoading,
    setError,
    setActionStatus,
    setBusyId,
    selectedIds,
    setSelectedIds,
    selectedRows,
    searchNames,
    setReloadKey,
    setSort,
  } = data

  async function runRowAction(row: UnmatchedRow, action: 'merge' | 'keep' | 'ignore') {
    setBusyId(row.id)
    setActionStatus('')
    try {
      await postJson(`/api/unmatched_folders/${encodeURIComponent(String(row.id))}/fix`, { action })
      setActionStatus(
        action === 'merge'
          ? 'Duplicate entry merged.'
          : action === 'keep'
            ? 'Entry returned to Unmatched.'
            : 'Entry ignored.',
      )
      setReloadKey((value) => value + 1)
    } catch (reason) {
      setError(reason)
    } finally {
      setBusyId(null)
    }
  }

  function toggleSelected(id: string | number) {
    setSelectedIds((current) => {
      const next = new Set(current)
      const key = String(id)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  async function runBatchAction(
    action: 'clear' | 'ignore_selected' | 'mark_kind' | 'merge' | 'keep' | 'ignore',
    kindValue?: string,
  ) {
    const ids = [...selectedIds]
    const selectedRowData = ids
      .map((id) => selectedRows.current.get(id))
      .filter((row): row is UnmatchedRow => Boolean(row))
    if (!ids.length) return
    if (action === 'clear' && !window.confirm(`Clear ${ids.length} selected unmatched entries?`))
      return
    if (action === 'ignore_selected' && !window.confirm(`Ignore ${ids.length} selected entries?`))
      return
    setLoading(true)
    setActionStatus('')
    try {
      const chunks: string[][] = []
      for (let index = 0; index < ids.length; index += 100)
        chunks.push(ids.slice(index, index + 100))
      if (action === 'clear') {
        let cleared = 0
        for (const batch of chunks) {
          const result = await postJson('/api/unmatched_folders/batch/clear', { ids: batch })
          cleared += Number(result?.cleared) || 0
        }
        setActionStatus(`Cleared ${cleared} selected ${entryLabel(cleared)}.`)
      } else if (action === 'ignore_selected') {
        const eligible = selectedRowData.filter((row) => row.status !== 'Ignore')
        let ignored = 0
        for (let index = 0; index < eligible.length; index += 100) {
          const results = await Promise.all(
            eligible.slice(index, index + 100).map(async (row) => {
              const response = await fetch(
                `/toggle_ignore_status/${encodeURIComponent(String(row.id))}`,
                {
                  method: 'POST',
                  credentials: 'same-origin',
                  headers: csrfHeaders({
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                  }),
                  body: JSON.stringify({}),
                },
              )
              return response.ok
            }),
          )
          ignored += results.filter(Boolean).length
        }
        setActionStatus(`Ignored ${ignored} of ${eligible.length} selected entries.`)
      } else if (action === 'mark_kind' && kindValue) {
        let marked = 0
        for (const batch of chunks) {
          const result = await postJson('/api/unmatched_folders/batch/mark_kind', {
            ids: batch,
            item_kind: kindValue,
          })
          marked += Number(result?.marked) || 0
        }
        setActionStatus(`Marked ${marked} of ${ids.length} selected as ${kindValue}.`)
      } else {
        const duplicateIds = selectedRowData
          .filter((row) => row.status === 'Duplicate')
          .map((row) => String(row.id))
        if (!duplicateIds.length) {
          setActionStatus('Select duplicate rows for Merge, Keep, or Ignore.')
          return
        }
        let fixed = 0
        for (let index = 0; index < duplicateIds.length; index += 100) {
          const result = await postJson('/api/unmatched_folders/batch/fix', {
            ids: duplicateIds.slice(index, index + 100),
            action,
          })
          fixed += Number(result?.fixed) || 0
        }
        setActionStatus(`Duplicate ${action}: ${fixed} of ${duplicateIds.length}.`)
      }
      setSelectedIds(new Set())
      selectedRows.current.clear()
      setReloadKey((value) => value + 1)
    } catch (reason) {
      setError(reason)
    } finally {
      setLoading(false)
    }
  }

  async function clearRows(statusFilter: 'all' | 'Unmatched') {
    const label = statusFilter === 'all' ? 'all unmatched-folder entries' : 'all Unmatched entries'
    if (
      !window.confirm(
        `Clear ${label}? This removes the database entries only; it does not delete files from storage.`,
      )
    )
      return
    setLoading(true)
    setError(null)
    setActionStatus('')
    let cleared = 0
    try {
      while (true) {
        const params = new URLSearchParams({
          status: statusFilter,
          limit: '100',
          offset: '0',
          paginate: '1',
          include: 'columns',
        })
        const result = await getJson(`/api/unmatched_folders?${params}`)
        const ids = Array.isArray(result?.items)
          ? result.items.map((row: UnmatchedRow) => String(row.id))
          : []
        if (!ids.length) break
        const batch = await postJson('/api/unmatched_folders/batch/clear', { ids })
        const removed = Number(batch?.cleared) || 0
        if (!removed)
          throw new Error('No entries were cleared; stopping to avoid repeating the request.')
        cleared += removed
      }
      setSelectedIds(new Set())
      selectedRows.current.clear()
      setActionStatus(`Cleared ${cleared} ${entryLabel(cleared)}. Storage files were not changed.`)
      setReloadKey((value) => value + 1)
    } catch (reason) {
      setError(reason)
    } finally {
      setLoading(false)
    }
  }

  async function toggleIgnore(row: UnmatchedRow, rowMenu: HTMLDetailsElement | null) {
    setBusyId(row.id)
    setError(null)
    try {
      const response = await fetch(`/toggle_ignore_status/${encodeURIComponent(String(row.id))}`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: csrfHeaders({
          'Content-Type': 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
        }),
        body: JSON.stringify({}),
      })
      if (!response.ok) throw new Error('Unable to change the folder status.')
      const payload = await response.json()
      // Reflect the new row state, then close the disclosure so its changed
      // Ignore/Unignore action is not left open over the refreshed table.
      if (rowMenu) {
        rowMenu.open = false
        rowMenu.querySelector('summary')?.focus()
      }
      setActionStatus(payload?.data?.message || payload?.message || 'Folder status updated.')
      setReloadKey((value) => value + 1)
    } catch (reason) {
      setError(reason)
    } finally {
      setBusyId(null)
    }
  }

  async function markKind(row: UnmatchedRow, kindValue: string, label: string) {
    setBusyId(row.id)
    setError(null)
    try {
      await postJson(`/api/unmatched_folders/${encodeURIComponent(String(row.id))}/mark_kind`, {
        item_kind: kindValue,
        name: row.search_name || undefined,
      })
      setActionStatus(`Marked as ${label}.`)
      setReloadKey((value) => value + 1)
    } catch (reason) {
      setError(reason)
    } finally {
      setBusyId(null)
    }
  }

  async function saveSearchName(row: UnmatchedRow) {
    const id = String(row.id)
    const value = (
      searchNames[id] ??
      row.search_name ??
      row.folder_name ??
      row.folder_path?.split(/[\\/]/).filter(Boolean).at(-1) ??
      ''
    ).trim()
    if (!value) {
      setActionStatus('Enter a search name.')
      return
    }
    setBusyId(row.id)
    setError(null)
    try {
      await postJson(`/api/unmatched_folders/${encodeURIComponent(id)}/name`, {
        search_name: value,
        display_name: value,
      })
      setActionStatus('Search name saved for Fix search. The folder on disk was not renamed.')
      setReloadKey((current) => current + 1)
    } catch (reason) {
      setError(reason)
    } finally {
      setBusyId(null)
    }
  }

  async function retryMatch(row: UnmatchedRow) {
    setBusyId(row.id)
    setError(null)
    try {
      const result = await postJson(
        `/api/unmatched_folders/${encodeURIComponent(String(row.id))}/retry_match`,
        {},
      )
      setActionStatus(
        result?.matched
          ? `Matched ${result.name || result.search_name || 'game'} using current metadata providers.`
          : `No unique metadata match found for ${result.search_name || 'folder'}.`,
      )
      setReloadKey((value) => value + 1)
    } catch (reason) {
      setError(reason)
    } finally {
      setBusyId(null)
    }
  }

  async function placeUpdate(row: UnmatchedRow) {
    const targetName = window.prompt(
      'Move this update into the game folder named:',
      row.suggested_search_name || '',
    )
    if (targetName === null) return
    if (!targetName.trim()) {
      setActionStatus('Enter the game folder name.')
      return
    }
    setBusyId(row.id)
    setError(null)
    try {
      const result = await postJson(
        `/api/unmatched_folders/${encodeURIComponent(String(row.id))}/place_update`,
        { game_root_name: targetName.trim() },
      )
      setActionStatus(
        result?.created_game_root
          ? `Created ${result.game_root_name} and moved the update into it.`
          : `Moved the update into ${result.game_root_name || targetName.trim()}.`,
      )
      setReloadKey((value) => value + 1)
    } catch (reason) {
      setError(reason)
    } finally {
      setBusyId(null)
    }
  }

  async function saveBadMatch(row: UnmatchedRow, reason: string) {
    let note: string | undefined
    if (reason === 'other') {
      const answer = window.prompt('What is wrong with this match?')
      if (answer === null || !answer.trim()) return
      note = answer.trim()
    }
    setBusyId(row.id)
    setError(null)
    try {
      await postJson(`/api/unmatched/${encodeURIComponent(String(row.id))}/bad_match`, {
        reason: reason || null,
        note,
      })
      setActionStatus(reason ? 'Bad-match feedback saved.' : 'Bad-match feedback cleared.')
      setReloadKey((value) => value + 1)
    } catch (cause) {
      setError(cause)
    } finally {
      setBusyId(null)
    }
  }

  async function deleteFolderFromDisk(row: UnmatchedRow) {
    const folderPath = String(row.folder_path || '')
    if (!window.confirm(`Are you sure you want to delete the folder ${folderPath} FROM DISK?`))
      return
    setBusyId(row.id)
    setError(null)
    try {
      const result = await postJson('/delete_folder', { folder_path: folderPath })
      setActionStatus(result?.message || 'Item deleted successfully. Database entry removed.')
      setReloadKey((value) => value + 1)
    } catch (reason) {
      const failure = reason as { status?: number; message?: string }
      if (
        failure.status === 404 &&
        /specified path does not exist/i.test(String(failure.message || ''))
      ) {
        setActionStatus('The path is already missing; its unmatched entry was removed.')
        setReloadKey((value) => value + 1)
      } else {
        setError(reason)
      }
    } finally {
      setBusyId(null)
    }
  }

  function toggleSort(key: typeof data.sort.key) {
    setSort((current) => ({ key, dir: current.key === key ? (current.dir === 1 ? -1 : 1) : 1 }))
  }
  return {
    runRowAction,
    toggleSelected,
    runBatchAction,
    clearRows,
    toggleIgnore,
    markKind,
    saveSearchName,
    retryMatch,
    placeUpdate,
    saveBadMatch,
    deleteFolderFromDisk,
    toggleSort,
  }
}
