/**
 * Library Management — reorder, multi-select Scan/Edit/Delete, force-delete bulk.
 * Shared by /libraries and Scan management → Libraries tab.
 *
 * Batch contract (W22-1 / UID-003):
 *   POST /api/admin/libraries/batch/scan  { library_uuids[], queue_policy? }
 *   POST /api/admin/libraries/batch/edit  { library_uuids[], scan_depth?, watch_enabled?, platform? }
 *   POST /api/admin/libraries/batch/delete { library_uuids|uuids, force? }
 * Soft-degrades to sequential single-library calls when a batch route 404/405.
 */
(function ensureAdminToast() {
  if (typeof window.odShowAdminToast === 'function') return;
  window.odShowAdminToast = function (message, variant) {
    if (!message) return;
    let host = document.getElementById('od-toast-host');
    if (!host) {
      host = document.createElement('div');
      host.id = 'od-toast-host';
      host.className = 'od-toast-host';
      host.setAttribute('aria-live', 'polite');
      document.body.appendChild(host);
    }
    const toneRaw = String(variant || 'success');
    const tone =
      toneRaw === 'danger' || toneRaw === 'error'
        ? 'error'
        : toneRaw === 'warning' || toneRaw === 'warn'
          ? 'warn'
          : toneRaw === 'info'
            ? 'info'
            : 'success';
    const el = document.createElement('div');
    el.className = `od-toast od-toast--${tone}`;
    el.textContent = String(message);
    host.appendChild(el);
    window.setTimeout(() => {
      el.classList.add('od-toast--out');
      window.setTimeout(() => {
        el.remove();
        if (host && !host.childElementCount) host.remove();
      }, 220);
    }, 3200);
  };
})();

document.addEventListener('DOMContentLoaded', function () {
  const panel = document.getElementById('odLibrariesPanel');
  if (!panel) return;

  const tbody = document.querySelector('#librariesTable tbody');
  if (tbody && typeof Sortable !== 'undefined') {
    new Sortable(tbody, {
      handle: '.drag-handle',
      animation: 150,
      onEnd: function () {
        const newOrder = Array.from(tbody.querySelectorAll('tr[data-library-uuid]')).map(
          (row) => row.dataset.libraryUuid,
        );
        fetch('/api/reorder_libraries', {
          method: 'POST',
          headers: CSRFUtils.getHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({ order: newOrder }),
        })
          .then((response) => response.json())
          .then((data) => {
            notify(
              data.status === 'success' ? 'Library order updated successfully' : 'Error updating library order',
              data.status === 'success' ? 'success' : 'error',
            );
          })
          .catch(() => notify('Error updating library order', 'error'));
      },
    });
  }

  const spinner = document.getElementById('deleteSpinner');
  const confirmDeleteButton = document.getElementById('confirmDeleteButton');
  const deleteModalEl = document.getElementById('deleteWarningModal');
  if (deleteModalEl && deleteModalEl.parentElement !== document.body) {
    document.body.appendChild(deleteModalEl);
  }
  const deleteWarningModal = bootstrap.Modal.getOrCreateInstance(deleteModalEl, {
    backdrop: true,
    keyboard: true,
    focus: true,
  });
  const deleteWarningMessage = document.getElementById('deleteWarningMessage');
  const deleteWarningList = document.getElementById('deleteWarningList');
  const deleteConfirmTyped = document.getElementById('deleteConfirmTyped');
  const deleteConfirmExpected = document.getElementById('deleteConfirmExpected');
  const deleteTypedConfirmBlock = document.getElementById('deleteTypedConfirmBlock');
  const deleteForceBlock = document.getElementById('deleteForceBlock');
  const deleteForceCheckbox = document.getElementById('deleteForceCheckbox');

  const baseDeleteUrl = panel.getAttribute('data-base-delete-url') || '';
  const batchDeleteUrl = panel.getAttribute('data-batch-delete-url') || '/api/admin/libraries/batch/delete';
  const batchScanUrl = panel.getAttribute('data-batch-scan-url') || '/api/admin/libraries/batch/scan';
  const batchEditUrl = panel.getAttribute('data-batch-edit-url') || '/api/admin/libraries/batch/edit';
  const scanUrl = panel.getAttribute('data-scan-url') || '/api/admin/libraries/scan';
  const watchUrlTemplate =
    panel.getAttribute('data-watch-url-template') || '/api/library/__UUID__/watch';
  const baseProgressUrl = panel.getAttribute('data-progress-url') || '';
  const baseCheckProgressUrl = panel.getAttribute('data-check-progress-url') || '';
  const editUrlTemplate =
    panel.getAttribute('data-edit-url-template') || '/admin/library/__UUID__';

  /** Enum name → label; mirrors oneirodex.platform.LibraryPlatform for batch edit. */
  const LIBRARY_PLATFORMS = [
    ['OTHER', 'Other'],
    ['PCWIN', 'PC Windows'],
    ['PCDOS', 'PC DOS'],
    ['MAC', 'Mac'],
    ['NES', 'Nintendo Entertainment System (NES)'],
    ['SNES', 'Super Nintendo Entertainment System (SNES)'],
    ['NGC', 'Nintendo GameCube'],
    ['N64', 'Nintendo 64'],
    ['GB', 'Nintendo GameBoy'],
    ['GBA', 'Nintendo GameBoy Advance'],
    ['GBC', 'Nintendo GameBoy Color'],
    ['NDS', 'Nintendo DS'],
    ['VB', 'Nintendo Virtual Boy'],
    ['WII', 'Nintendo Wii'],
    ['N3DS', 'Nintendo 3DS'],
    ['SWITCH', 'Nintendo Switch'],
    ['SEGA_MD', 'Sega Mega Drive/Genesis (MD)'],
    ['SEGA_MS', 'Sega Master System (MS)'],
    ['SEGA_CD', 'Sega CD'],
    ['SEGA_32X', 'Sega 32X'],
    ['SEGA_GG', 'Sega Game Gear (GG)'],
    ['SEGA_SATURN', 'Sega Saturn'],
    ['SEGA_DC', 'Sega Dreamcast'],
    ['ATARI_7800', 'Atari 7800'],
    ['ATARI_5200', 'Atari 5200'],
    ['ATARI_2600', 'Atari 2600'],
    ['LYNX', 'Atari Lynx'],
    ['JAGUAR', 'Atari Jaguar'],
    ['PCE', 'PC Engine'],
    ['PCFX', 'PC-FX'],
    ['NGP', 'Neo Geo Pocket'],
    ['WS', 'WonderSwan'],
    ['COLECO', 'ColecoVision'],
    ['THREEDO', '3DO'],
    ['VECTREX', 'Vectrex'],
    ['VICE_X64SC', 'Commodore 64'],
    ['VICE_X128', 'Commodore 128'],
    ['VICE_XVIC', 'Commodore VIC-20'],
    ['VICE_XPLUS4', 'Commodore Plus/4'],
    ['VICE_XPET', 'Commodore PET'],
    ['XBOX', 'Xbox'],
    ['X360', 'Xbox 360'],
    ['XONE', 'Xbox One'],
    ['XSX', 'Xbox Series X'],
    ['PSX', 'Sony Playstation (PSX)'],
    ['PS2', 'Sony PS2'],
    ['PS3', 'Sony PS3'],
    ['PS4', 'Sony PS4'],
    ['PS5', 'Sony PS5'],
    ['PSP', 'Sony PSP'],
    ['PSVITA', 'Sony PS Vita'],
    ['INTV', 'Intellivision'],
    ['CHAF', 'Fairchild Channel F'],
    ['O2EM', 'Magnavox Odyssey 2'],
    ['NEOGEO_CD', 'Neo Geo CD'],
    ['NEOGEO', 'Neo Geo AES'],
    ['ARCADE', 'Arcade'],
  ];

  let pendingDeleteTargets = [];
  let pendingEditTargets = [];

  const batchEditModalEl = document.getElementById('batchEditModal');
  if (batchEditModalEl && batchEditModalEl.parentElement !== document.body) {
    document.body.appendChild(batchEditModalEl);
  }
  const batchEditModal = batchEditModalEl
    ? bootstrap.Modal.getOrCreateInstance(batchEditModalEl, {
        backdrop: true,
        keyboard: true,
        focus: true,
      })
    : null;
  const batchEditScanDepth = document.getElementById('batchEditScanDepth');
  const batchEditWatch = document.getElementById('batchEditWatch');
  const batchEditPlatform = document.getElementById('batchEditPlatform');
  const batchEditApply = document.getElementById('batchEditApply');
  const batchEditOpenFull = document.getElementById('batchEditOpenFull');
  const batchEditList = document.getElementById('batchEditList');
  const batchEditMessage = document.getElementById('batchEditMessage');
  const batchEditTitle = document.getElementById('batchEditModalLabel');

  if (batchEditPlatform && batchEditPlatform.options.length <= 1) {
    LIBRARY_PLATFORMS.forEach(([name, label]) => {
      const opt = document.createElement('option');
      opt.value = name;
      opt.textContent = label;
      batchEditPlatform.appendChild(opt);
    });
  }

  function notify(message, tone) {
    if (typeof window.odShowAdminToast === 'function') {
      window.odShowAdminToast(message, tone);
      return;
    }
    if (window.$ && typeof $.notify === 'function') {
      $.notify(message, tone === 'warn' ? 'warn' : tone);
    }
  }

  function selectedRows() {
    return Array.from(document.querySelectorAll('.od-library-row-check:checked')).map((el) => ({
      uuid: el.getAttribute('data-library-uuid'),
      name: (el.getAttribute('data-library-name') || '').trim() || el.getAttribute('data-library-uuid'),
    }));
  }

  function syncSelectionUi() {
    const rows = selectedRows();
    const n = rows.length;
    const bar = document.getElementById('odLibrariesBatchBar');
    const countEls = [
      document.getElementById('odLibrariesSelectionCount'),
      document.getElementById('odLibrariesBatchCount'),
    ];
    countEls.forEach((el) => {
      if (el) el.textContent = n === 1 ? '1 selected' : `${n} selected`;
    });
    if (bar) bar.hidden = n === 0;
    const selectAll = document.getElementById('odLibrariesSelectAll');
    const checks = document.querySelectorAll('.od-library-row-check');
    if (selectAll && checks.length) {
      selectAll.checked = n > 0 && n === checks.length;
      selectAll.indeterminate = n > 0 && n < checks.length;
    }
  }

  function clearSelection() {
    document.querySelectorAll('.od-library-row-check').forEach((el) => {
      el.checked = false;
    });
    syncSelectionUi();
  }

  document.querySelectorAll('.od-library-row-check').forEach((el) => {
    el.addEventListener('change', syncSelectionUi);
  });
  const selectAll = document.getElementById('odLibrariesSelectAll');
  if (selectAll) {
    selectAll.addEventListener('change', function () {
      const on = selectAll.checked;
      document.querySelectorAll('.od-library-row-check').forEach((el) => {
        el.checked = on;
      });
      syncSelectionUi();
    });
  }
  const clearBtn = document.getElementById('odLibrariesBatchClear');
  if (clearBtn) clearBtn.addEventListener('click', clearSelection);

  function syncConfirmEnabled() {
    const force = deleteForceCheckbox && deleteForceCheckbox.checked;
    const bulk = pendingDeleteTargets.length > 1;
    if (bulk && force) {
      confirmDeleteButton.disabled = false;
      return;
    }
    const expected = deleteConfirmExpected ? deleteConfirmExpected.textContent : '';
    confirmDeleteButton.disabled = !typedMatches(expected);
  }

  function syncTypedConfirm(expected) {
    const phrase = String(expected || '').trim();
    if (deleteConfirmExpected) deleteConfirmExpected.textContent = phrase;
    if (deleteConfirmTyped) {
      deleteConfirmTyped.value = '';
      deleteConfirmTyped.placeholder = phrase;
      deleteConfirmTyped.focus();
    }
    syncConfirmEnabled();
  }

  function typedMatches(expected) {
    if (!deleteConfirmTyped) return false;
    return deleteConfirmTyped.value.trim() === String(expected || '').trim();
  }

  if (deleteConfirmTyped) {
    deleteConfirmTyped.addEventListener('input', syncConfirmEnabled);
  }
  if (deleteForceCheckbox) {
    deleteForceCheckbox.addEventListener('change', function () {
      if (deleteTypedConfirmBlock) {
        deleteTypedConfirmBlock.hidden = deleteForceCheckbox.checked && pendingDeleteTargets.length > 1;
      }
      syncConfirmEnabled();
    });
  }

  function openDeleteModal(targets) {
    pendingDeleteTargets = Array.isArray(targets) ? targets.filter((t) => t && t.uuid) : [];
    if (!pendingDeleteTargets.length) return;
    // React LibrariesPanel opens delete via window.odLibrariesAskDelete.

    const bulk = pendingDeleteTargets.length > 1;
    const title = document.getElementById('deleteWarningModalLabel');
    if (title) title.textContent = bulk ? 'Delete libraries' : 'Delete library';

    if (deleteForceCheckbox) deleteForceCheckbox.checked = false;
    if (deleteForceBlock) deleteForceBlock.hidden = !bulk;
    if (deleteTypedConfirmBlock) deleteTypedConfirmBlock.hidden = false;

    if (deleteWarningList) {
      if (bulk) {
        deleteWarningList.hidden = false;
        deleteWarningList.innerHTML = pendingDeleteTargets
          .map((t) => `<li>${escapeHtml(t.name)}</li>`)
          .join('');
      } else {
        deleteWarningList.hidden = true;
        deleteWarningList.innerHTML = '';
      }
    }

    if (bulk) {
      if (deleteWarningMessage) {
        deleteWarningMessage.textContent =
          `Delete ${pendingDeleteTargets.length} libraries? This removes library records and cannot be undone.`;
      }
      syncTypedConfirm(`DELETE ${pendingDeleteTargets.length} LIBRARIES`);
    } else {
      const name = pendingDeleteTargets[0].name;
      if (deleteWarningMessage) {
        deleteWarningMessage.textContent =
          `Delete library “${name}”? This removes the library record and cannot be undone.`;
      }
      syncTypedConfirm(name);
    }

    confirmDeleteButton.textContent = bulk ? 'Confirm Delete' : 'Confirm Delete';
    confirmDeleteButton.onclick = onConfirmDelete;
    deleteWarningModal.show();
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function showSpinner() {
    if (!spinner) return;
    spinner.style.display = 'flex';
    const progressText = document.getElementById('progressText');
    const progressBar = document.getElementById('progressBar');
    const progressFill = document.getElementById('progressFill');
    const progressCounter = document.getElementById('progressCounter');
    if (progressText) progressText.textContent = 'Starting deletion…';
    if (progressBar) progressBar.style.display = 'block';
    if (progressFill) progressFill.style.width = '0%';
    if (progressCounter) progressCounter.textContent = '0/0';
  }

  function hideSpinner() {
    if (spinner) spinner.style.display = 'none';
  }

  async function tryBatchDelete(uuids, force) {
    const res = await fetch(batchDeleteUrl, {
      method: 'POST',
      headers: CSRFUtils.getHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ library_uuids: uuids, uuids, force: Boolean(force) }),
    });
    if (res.status === 404 || res.status === 405) {
      return { missing: true };
    }
    let data = null;
    try {
      data = await res.json();
    } catch (_e) {
      data = null;
    }
    if (!res.ok) {
      const msg = (data && (data.message || data.error)) || `Batch delete failed (${res.status})`;
      throw new Error(msg);
    }
    return { missing: false, data, ok: true };
  }

  async function tryBatchScan(uuids) {
    const res = await fetch(batchScanUrl, {
      method: 'POST',
      headers: CSRFUtils.getHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ library_uuids: uuids, queue_policy: 'queue' }),
    });
    if (res.status === 404 || res.status === 405) {
      return { missing: true };
    }
    let data = null;
    try {
      data = await res.json();
    } catch (_e) {
      data = null;
    }
    if (!res.ok) {
      const msg = (data && (data.message || data.error)) || `Batch scan failed (${res.status})`;
      throw new Error(msg);
    }
    return { missing: false, data, ok: true };
  }

  async function sequentialScan(uuids) {
    let started = 0;
    let failed = 0;
    const results = [];
    for (const uuid of uuids) {
      try {
        const res = await fetch(scanUrl, {
          method: 'POST',
          headers: CSRFUtils.getHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({ library_uuid: uuid, queue_policy: 'queue' }),
        });
        const data = await res.json().catch(() => ({}));
        const status = data.status;
        if (res.ok && (status === 'started' || status === 'queued' || status === 'ok')) {
          started += 1;
          results.push({ uuid, ok: true, status });
        } else {
          failed += 1;
          results.push({ uuid, ok: false, status: status || 'rejected', error: data.message });
        }
      } catch (err) {
        failed += 1;
        results.push({ uuid, ok: false, status: 'error', error: String(err && err.message) });
      }
    }
    return { started, failed, results };
  }

  function parseWatchValue(raw) {
    const text = String(raw || '').trim().toLowerCase();
    if (!text) return undefined;
    if (text === 'default' || text === 'null' || text === 'follow') return null;
    if (text === 'on' || text === 'true' || text === '1') return true;
    if (text === 'off' || text === 'false' || text === '0') return false;
    return undefined;
  }

  function collectEditPatch() {
    const patch = {};
    if (batchEditScanDepth && batchEditScanDepth.value) {
      patch.scan_depth = Number(batchEditScanDepth.value);
    }
    if (batchEditWatch && batchEditWatch.value) {
      const watch = parseWatchValue(batchEditWatch.value);
      if (watch !== undefined) patch.watch_enabled = watch;
    }
    if (batchEditPlatform && batchEditPlatform.value) {
      patch.platform = batchEditPlatform.value;
    }
    return patch;
  }

  async function tryBatchEdit(uuids, patch) {
    const res = await fetch(batchEditUrl, {
      method: 'POST',
      headers: CSRFUtils.getHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ library_uuids: uuids, ...patch }),
    });
    if (res.status === 404 || res.status === 405) {
      return { missing: true };
    }
    let data = null;
    try {
      data = await res.json();
    } catch (_e) {
      data = null;
    }
    if (!res.ok) {
      const msg = (data && (data.message || data.error)) || `Batch edit failed (${res.status})`;
      throw new Error(msg);
    }
    return { missing: false, data, ok: true };
  }

  async function sequentialWatchEdit(uuids, watchEnabled) {
    let updated = 0;
    let failed = 0;
    for (const uuid of uuids) {
      const url = watchUrlTemplate.replace('__UUID__', encodeURIComponent(uuid));
      try {
        const res = await fetch(url, {
          method: 'PUT',
          headers: CSRFUtils.getHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({ watch_enabled: watchEnabled }),
        });
        if (res.ok) updated += 1;
        else failed += 1;
      } catch (_e) {
        failed += 1;
      }
    }
    return { updated, failed };
  }

  function openBatchEditModal(targets) {
    pendingEditTargets = Array.isArray(targets) ? targets.filter((t) => t && t.uuid) : [];
    if (!pendingEditTargets.length || !batchEditModal) return;

    const n = pendingEditTargets.length;
    if (batchEditTitle) {
      batchEditTitle.textContent = n === 1 ? 'Edit library' : `Edit ${n} libraries`;
    }
    if (batchEditMessage) {
      batchEditMessage.textContent =
        n === 1
          ? 'Apply shared fields, or open the full editor for name and image.'
          : `Apply shared fields to ${n} libraries. Leave a field unchanged to skip it. Rename/image need the full editor.`;
    }
    if (batchEditList) {
      if (n > 1) {
        batchEditList.hidden = false;
        batchEditList.innerHTML = pendingEditTargets
          .map((t) => `<li>${escapeHtml(t.name)}</li>`)
          .join('');
      } else {
        batchEditList.hidden = true;
        batchEditList.innerHTML = '';
      }
    }
    if (batchEditScanDepth) batchEditScanDepth.value = '';
    if (batchEditWatch) batchEditWatch.value = '';
    if (batchEditPlatform) batchEditPlatform.value = '';
    if (batchEditOpenFull) {
      if (n === 1) {
        batchEditOpenFull.hidden = false;
        batchEditOpenFull.href = editUrlTemplate.replace(
          '__UUID__',
          encodeURIComponent(pendingEditTargets[0].uuid),
        );
      } else {
        batchEditOpenFull.hidden = true;
        batchEditOpenFull.removeAttribute('href');
      }
    }
    batchEditModal.show();
  }

  async function onBatchEditApply() {
    const uuids = pendingEditTargets.map((t) => t.uuid);
    if (!uuids.length) return;
    const patch = collectEditPatch();
    if (!Object.keys(patch).length) {
      notify('Choose at least one field to change', 'info');
      return;
    }
    if (batchEditApply) batchEditApply.disabled = true;
    try {
      const batch = await tryBatchEdit(uuids, patch);
      if (batch.missing) {
        const onlyWatch =
          Object.keys(patch).length === 1 && Object.prototype.hasOwnProperty.call(patch, 'watch_enabled');
        if (onlyWatch) {
          const seq = await sequentialWatchEdit(uuids, patch.watch_enabled);
          if (batchEditModal) batchEditModal.hide();
          notify(
            seq.failed
              ? `Watch updated on ${seq.updated}, ${seq.failed} failed (batch API not ready — sequential).`
              : `Watch updated on ${seq.updated} libraries (batch API not ready — sequential).`,
            seq.failed ? 'warn' : 'success',
          );
          clearSelection();
          return;
        }
        if (uuids.length === 1) {
          if (batchEditModal) batchEditModal.hide();
          notify('Batch edit API not ready — opening full editor.', 'info');
          window.location.href = editUrlTemplate.replace('__UUID__', encodeURIComponent(uuids[0]));
          return;
        }
        notify(
          'Batch edit API not ready — open libraries one at a time from the row Edit button.',
          'warn',
        );
        return;
      }
      const data = batch.data || {};
      if (batchEditModal) batchEditModal.hide();
      const updated = Number(data.updated) || 0;
      const skipped = Number(data.skipped) || 0;
      const failed = Number(data.failed) || 0;
      if (failed === 0) {
        notify(
          data.message ||
            (updated
              ? `Updated ${updated} libraries${skipped ? ` (${skipped} unchanged)` : ''}.`
              : skipped
                ? 'No changes — selected libraries already match.'
                : 'Edit applied.'),
          'success',
        );
      } else {
        notify(
          data.message || `Edit: ${updated} updated, ${skipped} unchanged, ${failed} failed.`,
          'warn',
        );
      }
      clearSelection();
      if (updated > 0) {
        window.setTimeout(() => window.location.reload(), 600);
      }
    } catch (err) {
      console.error(err);
      notify(err.message || 'Edit failed', 'error');
    } finally {
      if (batchEditApply) batchEditApply.disabled = false;
    }
  }

  if (batchEditApply) {
    batchEditApply.addEventListener('click', function (event) {
      event.preventDefault();
      onBatchEditApply();
    });
  }

  async function sequentialDelete(uuids) {
    const jobs = [];
    for (const uuid of uuids) {
      const res = await fetch(baseDeleteUrl + uuid, {
        method: 'POST',
        headers: CSRFUtils.getHeaders({
          'Content-Type': 'application/x-www-form-urlencoded',
        }),
        body: new URLSearchParams({ csrf_token: CSRFUtils.getToken() }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.status !== 'started') {
        throw new Error(data.message || `Failed to start deletion for ${uuid}`);
      }
      jobs.push({ library_uuid: uuid, job_id: data.job_id, status: 'started' });
    }
    return jobs;
  }

  async function onConfirmDelete(confirmEvent) {
    confirmEvent.preventDefault();
    confirmEvent.stopPropagation();
    const bulk = pendingDeleteTargets.length > 1;
    const force = Boolean(deleteForceCheckbox && deleteForceCheckbox.checked);
    if (bulk && !force) {
      const expected = deleteConfirmExpected ? deleteConfirmExpected.textContent : '';
      if (!typedMatches(expected)) return;
    } else if (!bulk) {
      const name = pendingDeleteTargets[0].name;
      if (!typedMatches(name)) return;
    }

    deleteWarningModal.hide();
    showSpinner();
    const uuids = pendingDeleteTargets.map((t) => t.uuid);

    try {
      const batch = await tryBatchDelete(uuids, force || !bulk);
      let jobs = [];
      if (batch.missing) {
        jobs = await sequentialDelete(uuids);
        notify(
          force && bulk
            ? `Force-deleting ${uuids.length} libraries (batch API not ready — sequential).`
            : `Deleting ${uuids.length} libraries…`,
          'info',
        );
      } else {
        const data = batch.data || {};
        jobs = Array.isArray(data.jobs) ? data.jobs : [];
        if (!jobs.length && data.job_id) {
          jobs = [{ job_id: data.job_id, status: data.status || 'started' }];
        }
        notify(data.message || `Delete started for ${uuids.length} libraries.`, 'success');
      }

      const firstJob = jobs.find((j) => j && j.job_id);
      if (firstJob && firstJob.job_id) {
        startProgressTracking(firstJob.job_id);
      } else {
        hideSpinner();
        window.setTimeout(() => window.location.reload(), 800);
      }
    } catch (err) {
      console.error(err);
      hideSpinner();
      notify(err.message || 'Delete failed', 'error');
    }
  }

  document.querySelectorAll('.delete-btn').forEach((button) => {
    button.addEventListener('click', function (event) {
      event.preventDefault();
      event.stopPropagation();
      openDeleteModal([
        {
          uuid: this.getAttribute('data-library-uuid'),
          name: (this.getAttribute('data-library-name') || '').trim(),
        },
      ]);
    });
  });

  const batchDeleteBtn = document.getElementById('odLibrariesBatchDelete');
  if (batchDeleteBtn) {
    batchDeleteBtn.addEventListener('click', function () {
      const rows = selectedRows();
      if (!rows.length) {
        notify('Select one or more libraries first', 'info');
        return;
      }
      openDeleteModal(rows);
    });
  }

  const batchEditBtn = document.getElementById('odLibrariesBatchEdit');
  if (batchEditBtn) {
    batchEditBtn.addEventListener('click', function () {
      const rows = selectedRows();
      if (!rows.length) {
        notify('Select a library to edit', 'info');
        return;
      }
      openBatchEditModal(rows);
    });
  }

  const batchScanBtn = document.getElementById('odLibrariesBatchScan');
  if (batchScanBtn) {
    batchScanBtn.addEventListener('click', async function () {
      const rows = selectedRows();
      if (!rows.length) {
        notify('Select one or more libraries to scan', 'info');
        return;
      }
      const uuids = rows.map((r) => r.uuid);
      batchScanBtn.disabled = true;
      try {
        const batch = await tryBatchScan(uuids);
        if (batch.missing) {
          const seq = await sequentialScan(uuids);
          if (seq.failed === 0) {
            notify(
              seq.started === 1
                ? 'Scan started / queued for 1 library (batch API not ready — sequential).'
                : `Scan started / queued for ${seq.started} libraries (batch API not ready — sequential).`,
              'success',
            );
          } else {
            notify(
              `Scan: ${seq.started} ok, ${seq.failed} failed (need a prior Auto Scan folder?).`,
              'warn',
            );
          }
        } else {
          const data = batch.data || {};
          const started = Number(data.started) || 0;
          const queued = Number(data.queued) || 0;
          const skipped = Number(data.skipped) || 0;
          const failed = Number(data.failed) || 0;
          const okCount = started + queued;
          if (failed === 0 && skipped === 0) {
            notify(
              data.message ||
                (okCount === 1
                  ? 'Scan started / queued for 1 library'
                  : `Scan started / queued for ${okCount} libraries`),
              'success',
            );
          } else if (okCount > 0) {
            notify(
              data.message ||
                `Scan: ${started} started, ${queued} queued, ${skipped} skipped, ${failed} failed.`,
              'warn',
            );
          } else {
            notify(
              data.message ||
                `Scan: ${skipped} skipped, ${failed} failed (need a prior Auto Scan folder?).`,
              'warn',
            );
          }
        }
      } catch (err) {
        console.error(err);
        notify(err.message || 'Scan failed', 'error');
      } finally {
        batchScanBtn.disabled = false;
      }
    });
  }

  function startProgressTracking(jobId) {
    const progressText = document.getElementById('progressText');
    const progressBar = document.getElementById('progressBar');
    const progressFill = document.getElementById('progressFill');
    const progressCounter = document.getElementById('progressCounter');
    const eventSource = new EventSource(baseProgressUrl + jobId);

    eventSource.onmessage = function (event) {
      try {
        const data = JSON.parse(event.data);
        if (data.status === 'connected') return;
        if (data.current_game) {
          progressText.innerHTML = escapeHtml(data.message || 'Processing…') + '<br>' + escapeHtml(data.current_game);
        } else if (progressText) {
          progressText.textContent = data.message || 'Processing…';
        }
        if (data.total > 0 && progressFill && progressCounter) {
          const percentage = Math.round((data.current / data.total) * 100);
          progressFill.style.width = percentage + '%';
          progressCounter.textContent = `${data.current}/${data.total}`;
          if (progressBar) progressBar.style.display = 'block';
        }
        if (data.status === 'completed') {
          eventSource.close();
          if (progressFill) progressFill.style.width = '100%';
          setTimeout(() => {
            hideSpinner();
            notify(data.message || 'Delete completed', data.games_failed === 0 ? 'success' : 'warn');
            window.location.reload();
          }, 1200);
        }
        if (data.status === 'error') {
          eventSource.close();
          hideSpinner();
          notify('Error: ' + data.message, 'error');
        }
      } catch (error) {
        console.error('Error parsing progress data:', error);
      }
    };

    eventSource.onerror = function () {
      eventSource.close();
      startPollingFallback(jobId);
    };
  }

  function startPollingFallback(jobId) {
    const progressText = document.getElementById('progressText');
    const progressBar = document.getElementById('progressBar');
    const progressFill = document.getElementById('progressFill');
    const progressCounter = document.getElementById('progressCounter');
    if (progressText) progressText.textContent = 'Using fallback progress tracking…';

    function pollProgress() {
      fetch(baseCheckProgressUrl + jobId)
        .then((response) => response.json())
        .then((data) => {
          if (data.status === 'not_found') return;
          if (data.current_game) {
            progressText.innerHTML = escapeHtml(data.message || 'Processing…') + '<br>' + escapeHtml(data.current_game);
          } else if (progressText) {
            progressText.textContent = data.message || 'Processing…';
          }
          if (data.total > 0 && progressFill && progressCounter) {
            const percentage = Math.round((data.current / data.total) * 100);
            progressFill.style.width = percentage + '%';
            progressCounter.textContent = `${data.current}/${data.total}`;
            if (progressBar) progressBar.style.display = 'block';
          }
          if (data.status === 'completed') {
            if (progressFill) progressFill.style.width = '100%';
            setTimeout(() => {
              hideSpinner();
              notify(data.message || 'Delete completed', data.games_failed === 0 ? 'success' : 'warn');
              window.dispatchEvent(new CustomEvent('od-libraries-deleted'));
              window.location.reload();
            }, 1200);
            return;
          }
          if (data.status === 'error') {
            hideSpinner();
            notify('Error: ' + data.message, 'error');
            return;
          }
          setTimeout(pollProgress, 1000);
        })
        .catch(() => {
          hideSpinner();
          notify('Progress tracking failed', 'error');
        });
    }
    setTimeout(pollProgress, 500);
  }

  // Bridges for the React Libraries DataTable (same modals / batch edit apply).
  window.odLibrariesAskDelete = openDeleteModal;
  window.odLibrariesOpenBatchEdit = openBatchEditModal;

  syncSelectionUi();
});
