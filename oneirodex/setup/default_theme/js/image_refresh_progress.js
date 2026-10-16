/**
 * Image refresh progress — reported as a toast, not as a page banner.
 *
 * `/refresh_game_images/<uuid>` is a classic form POST from the tile menu: it
 * redirects and flashes, so the result arrived as an `.alert-image-refresh`
 * flash rendered at the top of `#content`. Being in the flow, it pushed the
 * entire library down the moment it appeared and pulled it back up when it
 * cleared — the whole grid jumping twice to report progress on one tile.
 *
 * Every other library notification is a toast, so this one is too. The alert is
 * lifted out of the flow into the shared toast host (`.od-toast`, the same
 * markup `utils/toast.js` builds) as soon as it is found, which fixes the layout
 * shift without touching the server flow that produced it: the flash is still
 * flashed, still carries the game uuid, and the polling below is unchanged.
 *
 * The same treatment now covers *every* flash on a shell page, not just this
 * one — see `rehomeFlashes`. On the member shell the flash container renders
 * above the SPA, so any flash at all shifted the whole grid down and back.
 *
 * Loaded by `base.html` **and** the member SPA renderer. It was only on the former,
 * and the member SPA extends the latter — so on the one page where the layout
 * shift was worst, none of this ran.
 */

(function () {
    'use strict';

    var HOST_ID = 'od-toast-host';

    /** The shared toast host, created on demand exactly as utils/toast.js does. */
    function toastHost() {
        var host = document.getElementById(HOST_ID);
        if (!host) {
            host = document.createElement('div');
            host.id = HOST_ID;
            host.className = 'od-toast-host';
            host.setAttribute('aria-live', 'polite');
            document.body.appendChild(host);
        }
        return host;
    }

    /**
     * Re-home a flash alert as a toast, preserving its text and data.
     *
     * Returns the element to keep tracking. The caller's later
     * `classList.add('alert-success')` still works — those classes are simply
     * not what draws it any more.
     */
    function asToast(alertElement) {
        var toast = document.createElement('div');
        toast.className = 'od-toast od-toast--info';
        toast.dataset.gameUuid = alertElement.dataset.gameUuid || '';

        var text = document.createElement('span');
        text.className = 'od-toast__text';
        text.textContent = (alertElement.textContent || '').trim() || 'Refreshing images…';
        toast.appendChild(text);

        var close = document.createElement('button');
        close.type = 'button';
        close.className = 'od-toast__close';
        close.setAttribute('aria-label', 'Dismiss notification');
        close.textContent = '×';
        close.addEventListener('click', function () {
            toast.remove();
        });
        toast.appendChild(close);

        toastHost().appendChild(toast);
        // Remove the banner only after the toast exists, so progress is never
        // unreported even for a frame.
        alertElement.remove();
        return { toast: toast, text: text };
    }

    /** Bootstrap's alert category -> the toast tone that means the same thing. */
    function toneFor(alertElement) {
        if (alertElement.classList.contains('alert-success')) return 'success';
        if (alertElement.classList.contains('alert-danger')) return 'error';
        if (alertElement.classList.contains('alert-warning')) return 'warn';
        return 'info';
    }

    /**
     * Every flash on a shell page becomes a toast, not just the image refresh.
     *
     * `partials/flash_messages.html` renders `.container-flash-messages` at the
     * top of the document, which on the member shell sits *above the SPA* and
     * pushes the entire library down the moment anything is flashed — then pulls
     * it back up when the alert is dismissed. One tile's worth of feedback moves
     * the whole grid twice. Toasts are what the rest of the member surfaces use,
     * so these join them.
     *
     * Only alerts still in the flow are moved, and the image-refresh one is left
     * for the tracker below, which needs to keep hold of it.
     */
    function rehomeFlashes() {
        var container = document.querySelector('.container-flash-messages');
        if (!container) {
            return;
        }
        var alerts = [].slice.call(container.querySelectorAll('.alert'));
        alerts.forEach(function (alertElement) {
            if (alertElement.classList.contains('alert-image-refresh')) {
                return;
            }
            var tone = toneFor(alertElement);
            var moved = asToast(alertElement);
            moved.toast.className = 'od-toast od-toast--' + tone;
            // Successes and notices are announcements and time out like every
            // other toast. Errors do not: this script also runs on base.html,
            // which serves login and registration, and a self-dismissing
            // "Invalid credentials" leaves the member staring at an unchanged
            // form with no idea why it did not work. They stay until the close
            // button is used.
            if (tone !== 'error') {
                setTimeout(function () {
                    moved.toast.remove();
                }, 6000);
            }
        });
        if (!container.querySelector('.alert')) {
            container.remove();
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        var imageRefreshAlert = document.querySelector('.alert-image-refresh');
        var gameUuid = imageRefreshAlert && imageRefreshAlert.dataset.gameUuid;
        if (imageRefreshAlert && gameUuid) {
            var moved = asToast(imageRefreshAlert);
            startProgressTracking(moved.toast, moved.text, gameUuid);
        }
        rehomeFlashes();
    });

    function startProgressTracking(toast, textNode, gameUuid) {
        var spinner = createSpinner();
        toast.insertBefore(spinner, toast.firstChild);

        var pollCount = 0;
        var maxPolls = 120; // 2 minutes max (120 * 1000ms)

        /** Settle the toast: final wording, tone, and a timed dismissal. */
        function finish(message, tone, keepSpinner) {
            textNode.textContent = message;
            toast.className = 'od-toast od-toast--' + tone;
            if (!keepSpinner) {
                spinner.remove();
            }
            setTimeout(function () {
                toast.remove();
            }, 3200);
        }

        var pollInterval = setInterval(function () {
            pollCount++;

            fetch('/check_image_refresh_progress/' + gameUuid, {
                method: 'GET',
                headers: CSRFUtils.getHeaders({
                    'X-Requested-With': 'XMLHttpRequest'
                })
            })
            .then(function (response) { return response.json(); })
            .then(function (data) {
                if (data.status === 'complete') {
                    updateSpinnerProgress(spinner, 100);
                    setTimeout(function () {
                        finish('Game updated, images downloaded successfully', 'success');
                    }, 500);
                    clearInterval(pollInterval);
                } else if (data.status === 'error') {
                    finish('Failed to refresh game images', 'error');
                    clearInterval(pollInterval);
                } else if (data.status === 'in_progress') {
                    updateSpinnerProgress(spinner, data.progress || 0);
                } else if (data.status === 'not_found' && pollCount > 5) {
                    // Not found after 5 polls: the job finished before we asked.
                    finish('Game updated successfully', 'success');
                    clearInterval(pollInterval);
                }

                if (pollCount >= maxPolls) {
                    finish('Image refresh is taking longer than expected', 'warn');
                    clearInterval(pollInterval);
                }
            })
            .catch(function (error) {
                console.error('Error checking progress:', error);
                // Don't stop polling on network errors, might be temporary
            });
        }, 1000); // Poll every second
    }

    function createSpinner() {
        var spinner = document.createElement('span');
        spinner.className = 'image-refresh-spinner';
        spinner.innerHTML = [
            '<svg viewBox="0 0 22 22">',
            '<circle class="spinner-circle-bg" cx="11" cy="11" r="10"></circle>',
            '<circle class="spinner-circle-progress" cx="11" cy="11" r="10"></circle>',
            '</svg>'
        ].join('');
        return spinner;
    }

    function updateSpinnerProgress(spinner, progress) {
        var circle = spinner.querySelector('.spinner-circle-progress');
        if (circle) {
            // Circle circumference = 2 * PI * r = 2 * 3.14159 * 10 = 62.83
            var circumference = 62.83;
            var offset = circumference - (progress / 100) * circumference;
            circle.style.strokeDashoffset = offset;
        }
    }
})();
