/** Admin → Integrations → Artwork & secondary → RetroAchievements. */
(function () {
  'use strict';

  const ENDPOINT = '/api/admin/integrations/retroachievements';

  function byId(id) {
    return document.getElementById(id);
  }

  function status(message, isError) {
    const el = byId('ra-save-status');
    if (!el) return;
    el.textContent = message || '';
    el.className = isError ? 'text-danger' : 'text-muted';
  }

  function applySettings(data) {
    byId('ra-admin-username').value = data.username || '';
    byId('ra-admin-api-key').value = '';
    byId('ra-admin-api-key').placeholder = data.has_key
      ? 'Key saved — enter a new key to replace it'
      : 'Paste web API key';
    byId('ra-username-source').textContent = data.username_source === 'environment'
      ? 'Using the username from the server environment.'
      : '';

    const clearRow = byId('ra-clear-key-row');
    clearRow.hidden = !data.has_key || data.key_source === 'environment';
    byId('ra-clear-key').checked = false;

    const envOwnsSettings = data.username_source === 'environment' && data.key_source === 'environment';
    byId('ra-save-settings').disabled = envOwnsSettings;
    if (envOwnsSettings) status('Connection is managed by the server environment.', false);
  }

  function readResponse(response) {
    return response.json().then(function (body) {
      if (!response.ok || !body || body.ok === false) {
        throw new Error((body && (body.error || body.message)) || ('HTTP ' + response.status));
      }
      return body;
    });
  }

  function load() {
    fetch(ENDPOINT, { credentials: 'same-origin' })
      .then(readResponse)
      .then(applySettings)
      .catch(function () {
        status('Could not load RetroAchievements settings.', true);
      });
  }

  function save() {
    const button = byId('ra-save-settings');
    const username = byId('ra-admin-username').value.trim();
    const apiKey = byId('ra-admin-api-key').value.trim();
    const body = { username: username };
    if (apiKey) body.api_key = apiKey;
    if (byId('ra-clear-key').checked) body.clear_api_key = true;

    button.disabled = true;
    status('Saving…', false);
    fetch(ENDPOINT, {
      method: 'PUT',
      credentials: 'same-origin',
      headers: CSRFUtils.getHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body),
    })
      .then(readResponse)
      .then(function (data) {
        applySettings(data);
        status('Connection saved.', false);
      })
      .catch(function (err) {
        button.disabled = false;
        status(err.message || 'Could not save RetroAchievements settings.', true);
      });
  }

  document.addEventListener('DOMContentLoaded', function () {
    if (!byId('retroAchievementsSettings')) return;
    load();
    byId('ra-save-settings').addEventListener('click', save);
  });
})();
