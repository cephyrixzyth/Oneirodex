/**
 * Preferences modal: theme swatch picker and preference saving.
 *
 * Timing: base.html loads this file from <head>, but the modal markup does not
 * exist then. It is fetched from settings.settings_panel and written into
 * #preferencesModalContainer only when the user opens Preferences, which is
 * long after DOMContentLoaded. Binding to #themeSelect or to the individual
 * swatches at load time therefore binds to nothing. Every listener below is
 * delegated from `document` instead: `document` exists before this script runs
 * and is never replaced, so the handlers keep working across any number of
 * modal injections.
 */
(function () {
    'use strict';

    var GRID_SELECTOR = '#themeSwatchGrid';
    // Tokens repainted for the live preview; --btn-primary is the legacy name
    // the older stylesheets still key on.
    var PREVIEW_TOKENS = ['--od-accent', '--btn-primary'];
    // Paired icon packs (Wave 2d) — keep in sync with PRESET_THEMES.
    var PRESET_ICON_PACKS = {
        aurora: 'pixel',
        ember: 'filled',
        violet: 'soft',
        forest: 'outline',
        ocean: 'duotone',
        rose: 'soft',
        mono: 'mono',
        sunset: 'filled',
        ice: 'soft',
        default: 'outline',
        'era-80s': 'pixel',
        'era-90s': 'filled',
        'era-late90s': 'duotone',
        'era-00s': 'soft',
        'era-arcade': 'filled',
        'era-desk': 'outline'
    };

    // Inline values displaced by the preview, so closing without saving restores
    // exactly what was there before (null = no preview active).
    var displacedTokens = null;
    var displacedEra = undefined;
    var displacedIconPack = undefined;
    var displacedIconPackHref = undefined;

    function notify(message, level) {
        if (window.jQuery && typeof window.jQuery.notify === 'function') {
            window.jQuery.notify(message, level);
        } else if (level === 'error') {
            console.error(message);
        } else {
            console.log(message);
        }
    }

    function swatches() {
        return Array.prototype.slice.call(
            document.querySelectorAll(GRID_SELECTOR + ' .theme-swatch')
        );
    }

    function syncSwatches(selected) {
        swatches().forEach(function (swatch) {
            var isSelected = swatch.dataset.theme === selected;
            swatch.classList.toggle('is-selected', isSelected);
            swatch.setAttribute('aria-pressed', isSelected ? 'true' : 'false');
        });
    }

    function syncFromSelect() {
        var select = document.getElementById('themeSelect');
        if (select) {
            syncSwatches(select.value);
        }
    }

    function swatchFor(value) {
        return swatches().filter(function (swatch) {
            return swatch.dataset.theme === value;
        })[0] || null;
    }

    /** The theme's accent, read off the rendered chip so JS holds no colours. */
    function accentOf(swatch) {
        var chip = swatch ? swatch.querySelector('.theme-swatch-chip') : null;
        if (!chip) {
            return null;
        }
        var colour = window.getComputedStyle(chip).backgroundColor;
        return colour && colour !== 'transparent' && colour !== 'rgba(0, 0, 0, 0)' ? colour : null;
    }

    function previewAccent(colour) {
        var root = document.documentElement;
        if (displacedTokens === null) {
            displacedTokens = PREVIEW_TOKENS.map(function (token) {
                return root.style.getPropertyValue(token);
            });
        }
        PREVIEW_TOKENS.forEach(function (token) {
            root.style.setProperty(token, colour);
        });
    }

    function previewEra(era) {
        var root = document.documentElement;
        if (!era) {
            return;
        }
        if (displacedEra === undefined) {
            displacedEra = root.getAttribute('data-era');
        }
        root.setAttribute('data-era', era);
    }

    function clearPreview() {
        if (displacedTokens === null && displacedEra === undefined && displacedIconPack === undefined) {
            return;
        }
        var root = document.documentElement;
        if (displacedTokens !== null) {
            PREVIEW_TOKENS.forEach(function (token, index) {
                var previous = displacedTokens[index];
                if (previous) {
                    root.style.setProperty(token, previous);
                } else {
                    root.style.removeProperty(token);
                }
            });
            displacedTokens = null;
        }
        if (displacedEra !== undefined) {
            if (displacedEra) {
                root.setAttribute('data-era', displacedEra);
            } else {
                root.removeAttribute('data-era');
            }
            displacedEra = undefined;
        }
        if (displacedIconPack !== undefined) {
            if (displacedIconPack) {
                root.setAttribute('data-icon-pack', displacedIconPack);
            } else {
                root.removeAttribute('data-icon-pack');
            }
            syncIconPackChips(displacedIconPack || '');
            var link = document.getElementById('od-icon-pack-css');
            if (link && displacedIconPackHref !== undefined) {
                if (displacedIconPackHref) {
                    link.setAttribute('href', displacedIconPackHref);
                } else {
                    link.removeAttribute('href');
                }
            }
            displacedIconPack = undefined;
            displacedIconPackHref = undefined;
        }
    }

    function selectTheme(value) {
        var select = document.getElementById('themeSelect');
        if (select && select.value !== value) {
            select.value = value;
            select.dispatchEvent(new Event('change', { bubbles: true }));
            return;
        }
        applySelection(value);
    }

    function applySelection(value) {
        syncSwatches(value);
        var swatch = swatchFor(value);
        var colour = accentOf(swatch);
        if (colour) {
            previewAccent(colour);
        }
        if (swatch && swatch.dataset.era) {
            previewEra(swatch.dataset.era);
        }
        var paired = (swatch && swatch.dataset.iconPack) || PRESET_ICON_PACKS[value];
        if (paired) {
            previewIconPack(paired);
        }
    }

    document.addEventListener('click', function (event) {
        var target = event.target;
        var swatch = target && target.closest ? target.closest('.theme-swatch') : null;
        if (!swatch || !swatch.closest(GRID_SELECTOR)) {
            return;
        }
        selectTheme(swatch.dataset.theme);
    });

    // `change` bubbles, so the native <select> reaches us the same way.
    document.addEventListener('change', function (event) {
        if (event.target && event.target.id === 'themeSelect') {
            applySelection(event.target.value);
        }
        if (event.target && event.target.id === 'iconPackSelect') {
            previewIconPack(event.target.value);
        }
    });

    function previewIconPack(packId) {
        if (!packId) return;
        if (displacedIconPack === undefined) {
            displacedIconPack = document.documentElement.getAttribute('data-icon-pack');
            var currentLink = document.getElementById('od-icon-pack-css');
            displacedIconPackHref = currentLink ? currentLink.getAttribute('href') : null;
        }
        document.documentElement.setAttribute('data-icon-pack', packId);
        syncIconPackChips(packId);
        // Swap pack stylesheet so preview matches saved look (not only data-icon-pack).
        var link = document.getElementById('od-icon-pack-css');
        if (link && link.href) {
            link.href = link.href.replace(
                /library\/icon-themes\/[^/]+\/pack\.css/,
                'library/icon-themes/' + encodeURIComponent(packId) + '/pack.css'
            );
        }
        document.querySelectorAll('#iconPackPreview .icon-pack-chip').forEach(function (chip) {
            chip.setAttribute('data-preview-active', chip.dataset.iconPack === packId ? '1' : '0');
        });
    }

    function syncIconPackChips(selected) {
        document.querySelectorAll('#iconPackPreview .icon-pack-chip').forEach(function (chip) {
            var on = chip.dataset.iconPack === selected;
            chip.classList.toggle('is-selected', on);
            chip.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
        var select = document.getElementById('iconPackSelect');
        if (select && select.value !== selected) {
            select.value = selected;
        }
    }

    document.addEventListener('click', function (event) {
        var target = event.target;
        var chip = target && target.closest ? target.closest('.icon-pack-chip') : null;
        if (!chip || !chip.closest('#iconPackPreview')) {
            return;
        }
        previewIconPack(chip.dataset.iconPack);
        var select = document.getElementById('iconPackSelect');
        if (select) {
            select.value = chip.dataset.iconPack;
            select.dispatchEvent(new Event('change', { bubbles: true }));
        }
    });

    // An unsaved preview must not outlive the modal.
    document.addEventListener('hidden.bs.modal', function (event) {
        if (event.target && event.target.id === 'preferencesModal') {
            clearPreview();
        }
    });

    document.addEventListener('submit', function (event) {
        var form = event.target;
        if (!form || form.id !== 'preferencesForm') {
            return;
        }
        event.preventDefault();

        fetch(form.action, {
            method: 'POST',
            body: new FormData(form),
            headers: CSRFUtils.getHeaders()
        })
        .then(function (response) {
            if (!response.ok) {
                throw new Error('Network response was not ok');
            }
            return response.json();
        })
        .then(function (data) {
            if (!data.success) {
                Object.values(data.errors || {}).forEach(function (error) {
                    notify(error[0], 'error');
                });
                return;
            }

            // The preview now matches what was saved, so let it stand until the
            // reload swaps in the real stylesheet.
            displacedTokens = null;
            displacedEra = undefined;
            displacedIconPack = undefined;
            displacedIconPackHref = undefined;

            var modalElement = document.getElementById('preferencesModal');
            var modal = window.bootstrap && modalElement
                ? window.bootstrap.Modal.getInstance(modalElement)
                : null;
            if (modal) {
                modal.hide();
            }

            notify(data.message, 'success');
            setTimeout(function () { window.location.reload(); }, 1000);
        })
        .catch(function (error) {
            console.error('Error:', error);
            notify('An error occurred while saving preferences', 'error');
        });
    });

    // Admin-only Reset Themes under Look. Same endpoint as Admin → Themes;
    // confirm then fetch so we do not navigate the window to /admin/themes.
    document.addEventListener('click', function (event) {
        var target = event.target;
        var button = target && target.closest
            ? target.closest('#odPrefsResetThemes')
            : null;
        if (!button) {
            return;
        }
        event.preventDefault();
        var url = button.getAttribute('data-reset-url');
        if (!url) {
            return;
        }
        var ok = window.confirm(
            'Reset all default themes? This overwrites modifications to shipped themes.'
        );
        if (!ok) {
            return;
        }
        button.disabled = true;
        fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: CSRFUtils.getHeaders({ 'Content-Type': 'application/json' }),
            body: '{}',
            redirect: 'follow'
        })
        .then(function (response) {
            if (!response.ok) {
                throw new Error('Theme reset failed');
            }
            notify('Default themes reset — reloading.', 'success');
            setTimeout(function () { window.location.reload(); }, 800);
        })
        .catch(function (error) {
            console.error('Error:', error);
            notify('Theme reset failed.', 'error');
            button.disabled = false;
        });
    });

    /**
     * Mark the saved theme as selected as soon as the modal is injected.
     * Scoped to the container base.html writes into, so this costs nothing on
     * the rest of the page.
     */
    function watchModalContainer() {
        var container = document.getElementById('preferencesModalContainer');
        if (!container || typeof MutationObserver === 'undefined') {
            return;
        }
        new MutationObserver(syncFromSelect).observe(container, { childList: true });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', watchModalContainer);
    } else {
        watchModalContainer();
    }

    // Exposed for pages that render the picker inline rather than injecting it.
    window.syncThemeSwatches = syncFromSelect;
})();
