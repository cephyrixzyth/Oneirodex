/* Extracted from the matching Jinja template so the page has no inline
 * <script>. Lives under static/js, not a theme copy — no Reset Themes. */
document.addEventListener('DOMContentLoaded', function() {
    function showStatus(message, kind) {
        const statusEl = document.getElementById('oidc-save-status');
        if (!statusEl) return;
        const alert = document.createElement('div');
        alert.className = 'alert alert-' + kind;
        alert.textContent = String(message ?? '');
        statusEl.replaceChildren(alert);
    }

    const readinessEl = document.getElementById('oidc-readiness');
    if (readinessEl) {
        fetch('/api/oidc/status', { credentials: 'same-origin' })
            .then(r => r.json())
            .then(data => {
                const cls = data.ready ? 'alert-success' : 'alert-secondary';
                readinessEl.className = 'alert ' + cls + ' mb-3';
                readinessEl.style.fontSize = '0.9rem';
                readinessEl.textContent = data.message || (data.ready ? 'OIDC ready' : 'OIDC not configured');
            })
            .catch(() => {
                readinessEl.textContent = 'Could not load OIDC readiness.';
            });
    }

    const saveBtn = document.getElementById('oidcSaveBtn');
    if (!saveBtn) return;

    saveBtn.addEventListener('click', async function() {
        const statusEl = document.getElementById('oidcSaveStatus');
        let roleMap;
        try {
            roleMap = JSON.parse(document.getElementById('oidc_role_map').value || '{}');
        } catch (e) {
            statusEl.innerHTML = '<div class="alert alert-danger">Role map must be valid JSON.</div>';
            return;
        }

        const payload = {
            oidc_enabled: document.getElementById('oidc_enabled').checked,
            oidc_display_name: document.getElementById('oidc_display_name').value.trim(),
            oidc_issuer_url: document.getElementById('oidc_issuer_url').value.trim(),
            oidc_client_id: document.getElementById('oidc_client_id').value.trim(),
            oidc_client_secret: document.getElementById('oidc_client_secret').value,
            oidc_redirect_uri: document.getElementById('oidc_redirect_uri').value.trim(),
            oidc_scopes: document.getElementById('oidc_scopes').value.trim(),
            oidc_role_claim: document.getElementById('oidc_role_claim').value.trim(),
            oidc_role_map: roleMap,
        };

        const headers = window.CSRFUtils.getHeaders({'Content-Type': 'application/json'});

        saveBtn.disabled = true;
        statusEl.textContent = 'Saving...';
        try {
            const response = await fetch(saveBtn.getAttribute('data-save-url'), {
                method: 'POST',
                headers,
                body: JSON.stringify(payload),
            });
            const data = await response.json();
            if (response.ok) {
                showStatus(data.message || 'Saved.', 'success');
            } else {
                showStatus(data.message || data.error || 'Save failed.', 'danger');
            }
        } catch (err) {
            showStatus('Network error while saving OIDC settings.', 'danger');
        } finally {
            saveBtn.disabled = false;
        }
    });
});
