/* Rail collapse / mobile drawer for the server-rendered shell. */
document.addEventListener('DOMContentLoaded', function() {
    const railToggle = document.getElementById('od-rail-toggle');
    const shell = document.getElementById('od-shell');
    const rail = shell && shell.querySelector('.od-rail');
    const content = document.getElementById('content');
    const topbar = shell && shell.querySelector('.od-topbar');
    const scrim = shell && shell.querySelector('.od-rail__scrim');
    if (!railToggle || !shell || !rail || !content || !topbar) return;

    const RAIL_KEY = 'od-rail-state';
    const mobileQuery = window.matchMedia('(max-width: 900px)');
    const focusableSelector = 'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary, [tabindex]:not([tabindex="-1"])';
    let opener = null;
    let desktopCollapsed = false;

    try {
        if (localStorage.getItem(RAIL_KEY) === 'collapsed' && !mobileQuery.matches) {
            desktopCollapsed = true;
        }
    } catch (e) { /* storage disabled — rail just will not remember */ }

    function focusableItems() {
        return Array.from(rail.querySelectorAll(focusableSelector)).filter(function(node) {
            if (node.hidden || node.getClientRects().length === 0) return false;
            // getClientRects() may still return boxes for links inside a
            // closed <details>. Keep the summary as a stop, but exclude its
            // collapsed contents so the drawer's Tab trap uses real stops.
            const closedDetails = node.closest('details:not([open])');
            return !closedDetails || node.matches('details:not([open]) > summary');
        });
    }

    function setDrawerOpen(open, restoreFocus) {
        shell.dataset.rail = open ? 'open' : (shell.dataset.rail === 'collapsed' ? 'collapsed' : 'expanded');
        railToggle.setAttribute('aria-expanded', String(open));
        railToggle.setAttribute('aria-controls', 'od-primary-navigation');
        rail.setAttribute('aria-hidden', String(!open));
        rail.inert = !open;
        if (open) {
            rail.setAttribute('role', 'dialog');
            rail.setAttribute('aria-label', 'Primary navigation');
            rail.setAttribute('aria-modal', 'true');
            content.inert = true;
            topbar.inert = true;
            if (scrim) scrim.hidden = false;
            window.requestAnimationFrame(function() {
                const first = focusableItems()[0];
                (first || rail).focus();
            });
        } else {
            rail.removeAttribute('role');
            rail.removeAttribute('aria-label');
            rail.removeAttribute('aria-modal');
            content.inert = false;
            topbar.inert = false;
            if (scrim) scrim.hidden = true;
            if (restoreFocus && opener && opener.isConnected) opener.focus();
            opener = null;
        }
    }

    function syncViewport() {
        if (mobileQuery.matches) {
            shell.dataset.rail = 'expanded';
            setDrawerOpen(false, false);
        } else {
            shell.dataset.rail = desktopCollapsed ? 'collapsed' : 'expanded';
            rail.removeAttribute('aria-hidden');
            rail.inert = false;
            rail.removeAttribute('role');
            rail.removeAttribute('aria-label');
            rail.removeAttribute('aria-modal');
            content.inert = false;
            topbar.inert = false;
            if (scrim) scrim.hidden = true;
            railToggle.setAttribute('aria-expanded', String(shell.dataset.rail !== 'collapsed'));
        }
    }

    syncViewport();
    if (mobileQuery.addEventListener) mobileQuery.addEventListener('change', syncViewport);
    else mobileQuery.addListener(syncViewport);

    railToggle.addEventListener('click', function() {
        if (mobileQuery.matches) {
            const open = shell.dataset.rail === 'open';
            if (!open) opener = railToggle;
            setDrawerOpen(!open, open);
            return;
        }
        const collapsed = shell.dataset.rail === 'collapsed';
        shell.dataset.rail = collapsed ? 'expanded' : 'collapsed';
        desktopCollapsed = !collapsed;
        railToggle.setAttribute('aria-expanded', String(collapsed));
        try {
            localStorage.setItem(RAIL_KEY, collapsed ? 'expanded' : 'collapsed');
        } catch (e) { /* not fatal */ }
    });

    const closeButton = rail.querySelector('.od-rail__close');
    if (closeButton) closeButton.addEventListener('click', function() { setDrawerOpen(false, true); });
    if (scrim) scrim.addEventListener('click', function() { setDrawerOpen(false, true); });

    rail.addEventListener('click', function(event) {
        const link = event.target.closest('a[href]');
        if (mobileQuery.matches && shell.dataset.rail === 'open' && link) {
            setDrawerOpen(false, false);
        }
    });

    document.addEventListener('keydown', function(event) {
        if (!mobileQuery.matches || shell.dataset.rail !== 'open') return;
        if (event.key === 'Escape') {
            event.preventDefault();
            setDrawerOpen(false, true);
            return;
        }
        if (event.key !== 'Tab') return;
        const items = focusableItems();
        if (!items.length) {
            event.preventDefault();
            rail.focus();
            return;
        }
        const first = items[0];
        const last = items[items.length - 1];
        if (event.shiftKey && (document.activeElement === first || !rail.contains(document.activeElement))) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && (document.activeElement === last || !rail.contains(document.activeElement))) {
            event.preventDefault();
            first.focus();
        }
    });
});
