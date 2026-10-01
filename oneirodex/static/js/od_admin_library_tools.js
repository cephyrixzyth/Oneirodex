/* Extracted from the matching Jinja template so the page has no inline
 * <script>. Lives under static/js, not a theme copy — no Reset Themes. */
(function() {
  if (!document.getElementById('doctorDryRunBtn')) return;

  const csrf = (window.CSRFUtils && CSRFUtils.getToken) ? CSRFUtils.getToken() : '';
  function headers() {
    return {'Content-Type': 'application/json', 'X-CSRFToken': csrf};
  }

  // Game names, folder paths and proposal candidates come from the filesystem
  // and store metadata. Anything interpolated into innerHTML goes through here.
  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  let lastDoctorRows = [];
  let lastRenamePlan = [];

  document.getElementById('doctorDryRunBtn').addEventListener('click', async () => {
    const roots = document.getElementById('doctorRoots').value.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
    const template = document.getElementById('doctorTemplate').value || '{title}';
    const limitRaw = document.getElementById('doctorLimit').value;
    const body = {roots, template};
    if (limitRaw) body.limit = parseInt(limitRaw, 10);
    const resp = await fetch('/api/library_tools/doctor/dry_run', {method:'POST', headers: headers(), body: JSON.stringify(body)});
    const data = await resp.json();
    lastDoctorRows = data.rows || [];
    document.getElementById('doctorWriteProposalsBtn').disabled = lastDoctorRows.length === 0;
    document.getElementById('doctorApplyRenamesBtn').disabled = lastDoctorRows.length === 0;
    document.getElementById('doctorOutput').textContent = JSON.stringify(data, null, 2);
  });

  document.getElementById('doctorWriteProposalsBtn').addEventListener('click', async () => {
    const resp = await fetch('/api/library_tools/doctor/write_proposals', {
      method:'POST', headers: headers(), body: JSON.stringify({rows: lastDoctorRows})
    });
    document.getElementById('doctorOutput').textContent = JSON.stringify(await resp.json(), null, 2);
  });

  document.getElementById('doctorApplyRenamesBtn').addEventListener('click', async () => {
    if (!confirm('Apply root-folder renames for all dry-run rows? This changes disk paths.')) return;
    const template = document.getElementById('doctorTemplate').value || '{title}';
    const resp = await fetch('/api/library_tools/doctor/apply_renames', {
      method:'POST', headers: headers(), body: JSON.stringify({rows: lastDoctorRows, template})
    });
    document.getElementById('doctorOutput').textContent = JSON.stringify(await resp.json(), null, 2);
  });

  document.getElementById('loadProposalsBtn').addEventListener('click', async () => {
    const box = document.getElementById('proposalsList');
    box.innerHTML = '<p>Scanning library roots for proposal sidecars…</p>';
    let data;
    try {
      const scanResp = await fetch('/api/library_tools/proposals/scan_roots', {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({}),
      });
      data = await scanResp.json();
      if (!scanResp.ok) {
        throw new Error(data.message || data.error || scanResp.statusText);
      }
    } catch (err) {
      // Fall back to game-path scan if root walk is unavailable.
      const resp = await fetch('/api/library_tools/proposals');
      data = await resp.json();
      if (!data.proposals || !data.proposals.length) {
        box.innerHTML = `<p>No proposal sidecars found. (${esc(err.message || 'scan failed')})</p>`;
        return;
      }
    }
    const proposals = data.proposals || data.rows || [];
    if (!proposals.length) {
      box.innerHTML = '<p>No proposal sidecars found under library roots or game folders.</p>';
      return;
    }
    box.innerHTML = proposals.map(p => {
      const proposal = p.proposal || p;
      const name = p.game_name || p.name || proposal.guessed_name || 'Unknown';
      const path = p.path || p.folder_path || '';
      const cands = ((proposal.candidates || p.candidates || [])).map(c => `${esc(c.name)} (${esc(c.score)})`).join(', ');
      const uuid = p.game_uuid || '';
      return `<div class="border rounded p-2 mb-2 od-proposal-row" data-path="${esc(path)}">
        <strong>${esc(name)}</strong>${uuid ? ` <code>${esc(uuid)}</code>` : ''}<br>
        <code>${esc(path)}</code><br>${cands || '<em>No candidates</em>'}
      </div>`;
    }).join('');
  });

  async function runRenameSearch() {
    const q = document.getElementById('renameSearch').value.trim();
    const hits = document.getElementById('renameSearchHits');
    if (!q) {
      hits.innerHTML = '';
      return;
    }
    hits.innerHTML = '<div class="list-group-item">Searching…</div>';
    try {
      const resp = await fetch('/api/admin/games_search?q=' + encodeURIComponent(q));
      const data = await resp.json();
      const rows = Array.isArray(data) ? data : (data.games || data.results || []);
      if (!rows.length) {
        hits.innerHTML = '<div class="list-group-item text-muted">No matches</div>';
        return;
      }
      hits.innerHTML = rows.map((g) => {
        const uuid = g.uuid || g.game_uuid || '';
        const name = g.name || 'Untitled';
        const path = g.full_disk_path || g.path || '';
        return `<button type="button" class="list-group-item list-group-item-action rename-hit"
          data-uuid="${esc(uuid)}" data-name="${esc(name)}">
          <strong>${esc(name)}</strong><br><code class="small">${esc(uuid)}</code>
          ${path ? `<br><span class="small text-muted">${esc(path)}</span>` : ''}
        </button>`;
      }).join('');
    } catch (err) {
      hits.innerHTML = `<div class="list-group-item text-danger">${esc(err.message || err)}</div>`;
    }
  }

  document.getElementById('renameSearchBtn').addEventListener('click', runRenameSearch);
  document.getElementById('renameSearch').addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter') {
      ev.preventDefault();
      runRenameSearch();
    }
  });
  document.getElementById('renameSearchHits').addEventListener('click', (ev) => {
    const btn = ev.target.closest('.rename-hit');
    if (!btn) return;
    document.getElementById('renameGameUuid').value = btn.dataset.uuid || '';
    document.getElementById('renameTitle').value = btn.dataset.name || '';
    document.getElementById('renameSelectedLabel').textContent = 'Selected: ' + (btn.dataset.name || btn.dataset.uuid);
    document.getElementById('renameSearchHits').innerHTML = '';
  });

  document.getElementById('renamePreviewBtn').addEventListener('click', async () => {
    const body = {
      game_uuid: document.getElementById('renameGameUuid').value.trim(),
      title: document.getElementById('renameTitle').value.trim() || undefined,
      year: document.getElementById('renameYear').value.trim() || undefined,
      template: document.getElementById('renameTemplate').value,
      rename_root: document.getElementById('renameRoot').checked,
      rename_top_level_media: document.getElementById('renameMedia').checked,
      move_letter_bucket: document.getElementById('renameBucket').checked
    };
    const resp = await fetch('/api/library_tools/rename/preview', {method:'POST', headers: headers(), body: JSON.stringify(body)});
    const data = await resp.json();
    lastRenamePlan = data.plan || [];
    const planBox = document.getElementById('renamePlan');
    planBox.innerHTML = lastRenamePlan.map((item, idx) => `
      <div class="form-check">
        <input class="form-check-input rename-item" type="checkbox" data-idx="${idx}" id="rn${idx}" checked>
        <label class="form-check-label" for="rn${idx}"><code>${esc(item.kind)}</code>: ${esc(item.from_path)} → ${esc(item.to_path)}</label>
      </div>`).join('') || '<p>No changes.</p>';
    document.getElementById('renameApplyBtn').disabled = lastRenamePlan.length === 0;
    document.getElementById('renameOutput').textContent = JSON.stringify(data, null, 2);
  });

  document.getElementById('renameApplyBtn').addEventListener('click', async () => {
    const selected = [];
    document.querySelectorAll('.rename-item:checked').forEach(el => {
      selected.push(lastRenamePlan[parseInt(el.dataset.idx, 10)]);
    });
    const body = {
      game_uuid: document.getElementById('renameGameUuid').value.trim(),
      plan: selected
    };
    const resp = await fetch('/api/library_tools/rename/apply', {method:'POST', headers: headers(), body: JSON.stringify(body)});
    document.getElementById('renameOutput').textContent = JSON.stringify(await resp.json(), null, 2);
  });

  async function runFreshness(body) {
    const out = document.getElementById('freshnessOutput');
    out.textContent = 'Refreshing… (this can take a while; store APIs are rate-limited)';
    try {
      const resp = await fetch('/api/admin/freshness/refresh', {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify(body),
      });
      let data;
      try {
        data = await resp.json();
      } catch (e) {
        out.textContent = `Bad response (${resp.status})`;
        return;
      }
      if (!resp.ok) {
        out.textContent = JSON.stringify(data, null, 2);
        return;
      }
      out.textContent = `Done: ${data.count || 0} updated, ${data.skipped_fresh || 0} skipped (fresh), ${(data.errors || []).length} errors.\n\n`
        + JSON.stringify(data, null, 2);
    } catch (err) {
      out.textContent = String(err);
    }
  }

  function freshnessBody(extra) {
    const libraryUuid = document.getElementById('freshnessLibrary').value;
    const body = {
      limit: parseInt(document.getElementById('freshnessLimit').value, 10) || 25,
      only_stale: document.getElementById('freshnessOnlyStale').checked,
      ...(extra || {}),
    };
    if (libraryUuid) body.library_uuid = libraryUuid;
    return body;
  }

  document.getElementById('freshnessRefreshBtn').addEventListener('click', async () => {
    await runFreshness(freshnessBody());
  });
  document.getElementById('freshnessAllBtn').addEventListener('click', async () => {
    await runFreshness(freshnessBody({ entire_library: true, limit: 500 }));
  });
})();
