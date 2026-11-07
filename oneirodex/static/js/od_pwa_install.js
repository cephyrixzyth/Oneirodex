/**
 * Install path for the member app — thin seats (TC-2b) and headsets (Quest).
 *
 * Two jobs, both small:
 *
 * 1. Register `/sw.js` at scope `/`. The worker is what makes the app
 *    installable at all, and what gives an installed window an offline page
 *    instead of a browser error. It caches static assets only — see app-sw.js.
 * 2. Own the install affordance. Chromium fires `beforeinstallprompt`, which we
 *    stash and replay from a button; every other browser installs through its
 *    own menu, so the button says so rather than pretending to be able to.
 *
 * Nothing here runs on an insecure origin: service workers need HTTPS (or
 * localhost), and an install button that cannot install is worse than none.
 * A LAN install therefore needs TLS — the docs say so plainly.
 */
(function () {
  'use strict';

  var deferredPrompt = null;
  var STORAGE_KEY = 'od-install-dismissed';

  function secureEnough() {
    return window.isSecureContext === true;
  }

  function alreadyInstalled() {
    return (
      window.matchMedia('(display-mode: standalone)').matches ||
      window.matchMedia('(display-mode: window-controls-overlay)').matches ||
      window.navigator.standalone === true
    );
  }

  function dismissed() {
    try {
      return window.localStorage.getItem(STORAGE_KEY) === '1';
    } catch (err) {
      return false;
    }
  }

  function remember() {
    try {
      window.localStorage.setItem(STORAGE_KEY, '1');
    } catch (err) {
      /* private window — the button just comes back next time */
    }
  }

  function registerWorker() {
    if (!('serviceWorker' in navigator) || !secureEnough()) return;
    navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(function () {
      // Optional: the app works perfectly well uninstalled.
    });
  }

  /** Sign-out drops whatever the worker cached for this browser profile. */
  function clearOnSignOut() {
    document.addEventListener(
      'click',
      function (event) {
        var action = event.target.closest && event.target.closest(
          'a[href$="/logout"], a[href*="/logout?"], button[data-action="logout"]',
        );
        if (!action) return;
        try {
          window.localStorage.removeItem('od.palette.recent');
        } catch (err) {
          // Restricted storage is optional; current code never writes this key.
        }
        if (!navigator.serviceWorker || !navigator.serviceWorker.controller) return;
        navigator.serviceWorker.controller.postMessage({ type: 'od-clear-caches' });
      },
      true,
    );
  }

  function mountButton() {
    var host = document.getElementById('od-install-app');
    if (!host) return;
    if (alreadyInstalled() || dismissed() || !secureEnough()) {
      host.hidden = true;
      return;
    }
    host.hidden = false;

    var action = host.querySelector('[data-od-install-action]');
    var hint = host.querySelector('[data-od-install-hint]');

    if (deferredPrompt) {
      if (action) {
        action.hidden = false;
        action.onclick = function () {
          var prompt = deferredPrompt;
          deferredPrompt = null;
          action.disabled = true;
          prompt.prompt();
          prompt.userChoice.then(function (choice) {
            if (choice && choice.outcome === 'accepted') {
              host.hidden = true;
            } else {
              action.disabled = false;
            }
          });
        };
      }
      if (hint) hint.hidden = true;
      return;
    }

    // No prompt event: Safari, Firefox, and headset browsers that install from
    // their own menu. Say where the control is instead of offering a dead one.
    if (action) action.hidden = true;
    if (hint) hint.hidden = false;
  }

  window.addEventListener('beforeinstallprompt', function (event) {
    event.preventDefault();
    deferredPrompt = event;
    mountButton();
  });

  window.addEventListener('appinstalled', function () {
    deferredPrompt = null;
    var host = document.getElementById('od-install-app');
    if (host) host.hidden = true;
  });

  document.addEventListener('click', function (event) {
    var dismiss = event.target.closest && event.target.closest('[data-od-install-dismiss]');
    if (!dismiss) return;
    remember();
    var host = document.getElementById('od-install-app');
    if (host) host.hidden = true;
  });

  registerWorker();
  clearOnSignOut();
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mountButton);
  } else {
    mountButton();
  }
})();
