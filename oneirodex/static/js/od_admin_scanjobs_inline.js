/* Extracted from the matching Jinja template so the page has no inline
 * <script>. Lives under static/js, not a theme copy — no Reset Themes. */
    // Mirrors icons.html's 'download' and 'trash' glyphs — the icon macro can't run
    // inside these JS-built table rows, so the SVG markup is duplicated here.
    const ICON_DOWNLOAD_SVG = (document.getElementById('od-icon-download') || {}).innerHTML || '';
    const ICON_TRASH_SVG = (document.getElementById('od-icon-trash') || {}).innerHTML || '';

    function onLibraryChange(libraryUuid, scanType) {
        // Update the URL with the new library_uuid parameter and active_tab
        const url = new URL(window.location.href);
        url.searchParams.set('library_uuid', libraryUuid);
        url.searchParams.set('active_tab', scanType === 'manual' ? 'manual' : 'auto');
        window.location.href = url.toString();
    }

    // Image Queue functionality
    let currentPage = 1;

    function escapeHtml(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    // Initialize image queue when its page is present.
    document.addEventListener('DOMContentLoaded', function() {
        // Image queue is its own page (`?active_tab=image_queue`); the panel
        // is only in the DOM when that page rendered.
        const imageQueue = document.getElementById('imageQueue');
        if (imageQueue) {
            loadImageQueue();
        }
    });

    // Load image queue with filters
    async function loadImageQueue() {
        const statusFilter = document.getElementById('status-filter')?.value || 'all';
        const typeFilter = document.getElementById('type-filter')?.value || 'all';
        const groupByGame = document.getElementById('group-by-game')?.checked || false;
        // Grouping needs the whole filtered set in view, not just one page.
        const perPage = groupByGame ? 500 : 50;

        const params = new URLSearchParams({
            page: groupByGame ? 1 : currentPage,
            per_page: perPage,
            status: statusFilter,
            type: typeFilter
        });

        try {
            const tableBody = document.getElementById('image-table-body');
            if (tableBody) {
                tableBody.innerHTML = '<tr><td colspan="7" class="text-center"><span class="od-spinner" aria-hidden="true"></span> Loading...</td></tr>';
            }

            const response = await fetch(`/admin/api/image_queue_list?${params}`);
            const data = await response.json();

            if (data.error) {
                showMessage('Error loading images: ' + data.error, 'danger');
                return;
            }

            if (groupByGame) {
                renderImageTableGrouped(data.images);
                const paginationNav = document.getElementById('pagination-nav');
                if (paginationNav) paginationNav.style.display = 'none';
            } else {
                renderImageTable(data.images);
                renderPagination(data.pagination);
            }

        } catch (error) {
            console.error('Error loading image queue:', error);
            showMessage('Error loading image queue', 'danger');
            const tableBody = document.getElementById('image-table-body');
            if (tableBody) {
                tableBody.innerHTML = '<tr><td colspan="7" class="text-center text-danger">Error loading data</td></tr>';
            }
        }
    }

    function statusBadgeFor(image) {
        const status = image.status || (image.is_downloaded ? 'downloaded' : 'pending');
        if (status === 'downloaded') {
            return image.file_missing
                ? '<span class="badge bg-danger" title="Marked downloaded but the file is missing on disk">File missing</span>'
                : '<span class="badge bg-success">Downloaded</span>';
        }
        if (status === 'failed') {
            const reason = image.last_error ? escapeHtml(image.last_error) : 'Download failed for an unknown reason.';
            return `<span class="badge bg-danger" data-toggle="tooltip" title="${reason}">Failed</span>`;
        }
        return '<span class="badge bg-warning">Pending</span>';
    }

    function previewCellFor(image) {
        if (image.local_url) {
            return `<img src="${escapeHtml(image.local_url)}" alt="" class="image-queue-thumb" loading="lazy">`;
        }
        return '<span class="image-queue-thumb image-queue-thumb--empty" aria-hidden="true"></span>';
    }

    function actionsCellFor(image) {
        const status = image.status || (image.is_downloaded ? 'downloaded' : 'pending');
        const retryOrDownload = status === 'failed'
            ? `<button type="button" class="btn btn-sm btn-warning me-1" data-od-click="downloadSingle" data-od-arg="${image.id}" title="Retry download">
                    ${ICON_DOWNLOAD_SVG} Retry
               </button>`
            : (status === 'pending'
                ? `<button type="button" class="btn btn-sm btn-success me-1" data-od-click="downloadSingle" data-od-arg="${image.id}" title="Download">
                        ${ICON_DOWNLOAD_SVG}
                   </button>`
                : '');
        return `
            ${retryOrDownload}
            <button type="button" class="btn btn-sm btn-danger" data-od-click="deleteSingle" data-od-arg="${image.id}" title="Delete">
                ${ICON_TRASH_SVG}
            </button>
        `;
    }

    function imageRowHtml(image, { showGame = true } = {}) {
        const typeBadge = image.image_type === 'cover' ?
            '<span class="badge bg-primary">Cover</span>' :
            '<span class="badge bg-info">Screenshot</span>';

        const downloadUrl = image.download_url ?
            escapeHtml(image.download_url.substring(0, 50)) + '...' : 'No URL';

        return `
            <tr>
                <td>${previewCellFor(image)}</td>
                <td>
                    ${showGame ? `<strong>${escapeHtml(image.game_name)}</strong><br><small class="text-muted">${escapeHtml(image.game_uuid)}</small>` : ''}
                </td>
                <td>${typeBadge}</td>
                <td>${statusBadgeFor(image)}</td>
                <td><small>${downloadUrl}</small></td>
                <td><small>${escapeHtml(image.created_at)}</small></td>
                <td>${actionsCellFor(image)}</td>
            </tr>
        `;
    }

    // Render image table (flat, paginated)
    function renderImageTable(images) {
        const tbody = document.getElementById('image-table-body');
        if (!tbody) return;

        if (images.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" class="text-center">No images found</td></tr>';
            return;
        }

        tbody.innerHTML = images.map(image => imageRowHtml(image)).join('');
    }

    // Render image table grouped by game — clearer status at a glance per title.
    function renderImageTableGrouped(images) {
        const tbody = document.getElementById('image-table-body');
        if (!tbody) return;

        if (images.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" class="text-center">No images found</td></tr>';
            return;
        }

        const groups = new Map();
        images.forEach(image => {
            const key = image.game_uuid || 'unknown';
            if (!groups.has(key)) {
                groups.set(key, { name: image.game_name || 'Unknown', uuid: image.game_uuid || '', items: [] });
            }
            groups.get(key).items.push(image);
        });

        const sortedGroups = Array.from(groups.values()).sort((a, b) => a.name.localeCompare(b.name));

        const html = sortedGroups.map(group => {
            const failedCount = group.items.filter(i => (i.status || (i.is_downloaded ? 'downloaded' : 'pending')) === 'failed').length;
            const pendingCount = group.items.filter(i => (i.status || (i.is_downloaded ? 'downloaded' : 'pending')) === 'pending').length;
            const summary = [
                failedCount ? `<span class="badge bg-danger ms-1">${failedCount} failed</span>` : '',
                pendingCount ? `<span class="badge bg-warning ms-1">${pendingCount} pending</span>` : ''
            ].join('');
            const headerRow = `
                <tr class="image-queue-group-header">
                    <td colspan="7">
                        <strong>${escapeHtml(group.name)}</strong>
                        <small class="text-muted">${escapeHtml(group.uuid)}</small>
                        ${summary}
                        ${group.uuid ? `<a class="btn btn-sm btn-outline-light ms-2" href="/admin/art_studio?game=${encodeURIComponent(group.uuid)}&name=${encodeURIComponent(group.name)}#images">Open picker</a>
                        <a class="btn btn-sm btn-outline-secondary ms-1" href="/edit_game_images/${encodeURIComponent(group.uuid)}">Classic edit</a>` : ''}
                    </td>
                </tr>
            `;
            const itemRows = group.items.map(image => imageRowHtml(image, { showGame: false })).join('');
            return headerRow + itemRows;
        }).join('');

        tbody.innerHTML = html;
    }

    // Render pagination
    function renderPagination(pagination) {
        const paginationNav = document.getElementById('pagination-nav');
        const paginationUl = document.getElementById('pagination');
        if (!paginationNav || !paginationUl) return;

        if (pagination.pages <= 1) {
            paginationNav.style.display = 'none';
            return;
        }

        paginationNav.style.display = 'block';

        let html = `
            <li class="page-item ${!pagination.has_prev ? 'disabled' : ''}">
                <a class="page-link" href="#" data-od-click="changePage" data-od-arg="${pagination.page - 1}">Previous</a>
            </li>
        `;

        // Show page numbers (simplified)
        const startPage = Math.max(1, pagination.page - 2);
        const endPage = Math.min(pagination.pages, pagination.page + 2);

        for (let i = startPage; i <= endPage; i++) {
            html += `
                <li class="page-item ${i === pagination.page ? 'active' : ''}">
                    <a class="page-link" href="#" data-od-click="changePage" data-od-arg="${i}">${i}</a>
                </li>
            `;
        }

        html += `
            <li class="page-item ${!pagination.has_next ? 'disabled' : ''}">
                <a class="page-link" href="#" data-od-click="changePage" data-od-arg="${pagination.page + 1}">Next</a>
            </li>
        `;

        paginationUl.innerHTML = html;
    }

    // Change page
    function changePage(page) {
        if (page < 1) return;
        currentPage = page;
        loadImageQueue();
    }

    // Apply filters
    function applyFilters() {
        currentPage = 1;
        loadImageQueue();
    }

    // Refresh queue
    function refreshQueue() {
        loadImageQueue();
    }

    // Download batch
    async function downloadBatch(size) {
        try {
            const response = await fetch('/admin/api/download_images', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': CSRFUtils.getToken()
                },
                body: JSON.stringify({ batch_size: size })
            });

            const result = await response.json();

            if (result.success) {
                showMessage(result.message, result.failed ? 'warning' : 'success');
                loadImageQueue();
            } else {
                showMessage('Download failed: ' + result.message, 'danger');
            }

        } catch (error) {
            console.error('Error downloading batch:', error);
            showMessage('Error downloading batch: ' + error.message, 'danger');
        }
    }

    // Download (or retry) a single image
    async function downloadSingle(imageId) {
        try {
            const response = await fetch('/admin/api/download_images', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': CSRFUtils.getToken()
                },
                body: JSON.stringify({ image_ids: [imageId] })
            });

            const result = await response.json();

            if (result.success && result.downloaded > 0) {
                showMessage(result.message, 'success');
                loadImageQueue();
            } else if (result.success) {
                const reason = result.errors && result.errors[0] ? result.errors[0].error : 'unknown reason';
                showMessage(`Download failed: ${reason}`, 'danger');
                loadImageQueue();
            } else {
                showMessage('Download failed: ' + result.message, 'danger');
            }

        } catch (error) {
            console.error('Error downloading image:', error);
            showMessage('Error downloading image', 'danger');
        }
    }

    // Retry every image the queue previously failed to download
    async function retryFailed() {
        const btn = document.getElementById('retryFailedBtn');
        if (btn) btn.disabled = true;
        try {
            const response = await fetch('/admin/api/download_images', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': CSRFUtils.getToken()
                },
                body: JSON.stringify({ retry_failed: true })
            });

            const result = await response.json();

            if (result.success) {
                showMessage(result.message, result.failed ? 'warning' : 'success');
                loadImageQueue();
            } else {
                showMessage('Retry failed: ' + result.message, 'danger');
            }
        } catch (error) {
            console.error('Error retrying failed images:', error);
            showMessage('Error retrying failed images', 'danger');
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    // Auto-pick best available artwork via Backend cover policy.
    async function autoPickBest() {
        const btn = document.getElementById('autoPickBtn');
        if (btn) btn.disabled = true;
        try {
            const response = await fetch('/admin/api/covers/batch/apply', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': CSRFUtils.getToken()
                },
                body: JSON.stringify({
                    policy: 'sgdb_then_igdb_then_generate',
                    missing_cover: true,
                    limit_games: 25,
                    image_type: document.getElementById('type-filter')?.value || 'cover'
                })
            });
            const result = await response.json().catch(() => ({}));
            if (response.ok) {
                const applied = result.applied ?? 0;
                const failed = result.failed ?? 0;
                showMessage(
                    result.message || `Auto-pick finished — applied ${applied}, failed ${failed}`,
                    failed ? 'warning' : 'success'
                );
                loadImageQueue();
            } else {
                showMessage(
                    result.error || result.message || `Auto-pick failed (HTTP ${response.status})`,
                    'danger'
                );
            }
        } catch (error) {
            showMessage('Auto-pick error: ' + (error.message || error), 'danger');
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    // Delete single image
    async function deleteSingle(imageId) {
        if (!confirm('Are you sure you want to delete this image?')) {
            return;
        }

        try {
            const response = await fetch(`/admin/api/delete_image/${imageId}`, {
                method: 'DELETE',
                headers: {
                    'X-CSRFToken': CSRFUtils.getToken()
                }
            });

            const result = await response.json();

            if (result.success) {
                showMessage(result.message, 'success');
                loadImageQueue();
            } else {
                showMessage('Delete failed: ' + result.message, 'danger');
            }

        } catch (error) {
            console.error('Error deleting image:', error);
            showMessage('Error deleting image', 'danger');
        }
    }

    // Show message
    function showMessage(message, type = 'info') {
        const messagesDiv = document.getElementById('messages');
        if (!messagesDiv) return;

        const messageDiv = document.createElement('div');
        messageDiv.className = `alert alert-${type} alert-dismissible fade show`;
        const messageText = document.createElement('span');
        messageText.textContent = String(message ?? '');
        const closeButton = document.createElement('button');
        closeButton.type = 'button';
        closeButton.className = 'btn-close';
        closeButton.setAttribute('data-bs-dismiss', 'alert');
        closeButton.setAttribute('aria-label', 'Close');
        messageDiv.append(messageText, closeButton);

        messagesDiv.appendChild(messageDiv);

        setTimeout(() => {
            if (messageDiv.parentNode) {
                messageDiv.remove();
            }
        }, 5000);
    }

    // Show permissions modal if redirected with show_permissions_modal parameter
    document.addEventListener('DOMContentLoaded', function() {
        const urlParams = new URLSearchParams(window.location.search);
        if (urlParams.get('show_permissions_modal') === 'true') {
            const modal = new bootstrap.Modal(document.getElementById('permissionsErrorModal'));
            modal.show();

            // Clear the session flag after showing modal
            fetch('/admin/clear_permission_errors', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': CSRFUtils.getToken()
                }
            });

            // Remove the parameter from URL without reloading
            urlParams.delete('show_permissions_modal');
            const newUrl = window.location.pathname + '?' + urlParams.toString();
            window.history.replaceState({}, '', newUrl);
        }
    });
