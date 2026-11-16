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

  var RETIRED_CACHE = 'oneirodex-vr-v1';
  var PRIVACY_TIMEOUT = 10000;
  var legacyRetired = false;
  var retiredControllers = [];

  function safeFallback() {
    var controller = navigator.serviceWorker && navigator.serviceWorker.controller;
    return legacyRetired && (!ownedWorker(controller, '/vr/sw.js') || retiredControllers.indexOf(controller) !== -1);
  }

  function ownedWorker(worker, path) {
    if (!worker) return false;
    var url = new URL(worker.scriptURL, window.location.href);
    return url.origin === window.location.origin && url.pathname === path;
  }

  function workers(registration) {
    return [registration.active, registration.waiting, registration.installing].filter(Boolean);
  }

  function vrRegistration(registration) {
    var scope = new URL(registration.scope);
    var entries = workers(registration);
    return scope.origin === window.location.origin &&
      (scope.pathname === '/vr' || scope.pathname === '/vr/') && entries.length &&
      entries.every(function (worker) { return ownedWorker(worker, '/vr/sw.js'); });
  }

  function pause() {
    return new Promise(function (resolve) { window.setTimeout(resolve, 50); });
  }

  function acknowledge(worker, type) {
    return new Promise(function (resolve) {
      var channel = new MessageChannel();
      var timer = window.setTimeout(function () { finish(false); }, 300);
      function finish(value) {
        window.clearTimeout(timer);
        channel.port1.close();
        channel.port2.close();
        resolve(value);
      }
      channel.port1.onmessage = function (event) { finish(event.data === type); };
      try { worker.postMessage({ type: type }, [channel.port2]); }
      catch (err) { finish(false); }
    });
  }

  async function retireRegistration(registration, deadline) {
    var previous = workers(registration);
    if (registration.active && await acknowledge(registration.active, 'od-vr-retired')) {
      retiredControllers.push(registration.active);
      await registration.unregister();
      return true;
    }
    // Updating replaces the caching worker only after its pending events finish.
    // Unregister alone leaves both its current clients and pending writes alive.
    await registration.update().catch(function () {});
    while (Date.now() < deadline) {
      var entries = workers(registration);
      if (entries.some(function (worker) { return !ownedWorker(worker, '/vr/sw.js'); })) return false;
      var active = registration.active;
      var retired = active && previous.indexOf(active) === -1 && active.state === 'activated' &&
        await acknowledge(active, 'od-vr-retired');
      if (retired) retiredControllers.push(active);
      if (retired || previous.every(function (worker) { return worker.state === 'redundant'; })) {
        await registration.unregister();
        return true;
      }
      await pause();
    }
    return false;
  }

  async function migrateWorker() {
    if (!('serviceWorker' in navigator) || !secureEnough()) {
      legacyRetired = true;
      return true;
    }
    var service = navigator.serviceWorker;
    var deadline = Date.now() + PRIVACY_TIMEOUT;
    var registrations = await service.getRegistrations();
    var mixedLegacy = registrations.some(function (registration) {
      var scope = new URL(registration.scope);
      return scope.origin === window.location.origin &&
        (scope.pathname === '/vr' || scope.pathname === '/vr/') &&
        workers(registration).some(function (worker) { return ownedWorker(worker, '/vr/sw.js'); }) &&
        !vrRegistration(registration);
    });
    if (mixedLegacy) return false;
    var legacy = registrations.filter(vrRegistration);
    legacyRetired = false;
    for (var registration of legacy) {
      if (!await retireRegistration(registration, deadline)) return false;
    }
    // All owned registrations are gone. A replacement retirement controller is
    // safe only after its policy acknowledgement; an old URL alone proves nothing.
    if (ownedWorker(service.controller, '/vr/sw.js') && retiredControllers.indexOf(service.controller) === -1) {
      if (!await acknowledge(service.controller, 'od-vr-retired')) return false;
      retiredControllers.push(service.controller);
    }
    await caches.delete(RETIRED_CACHE);
    legacyRetired = true;
    try {
      var root = await service.register('/sw.js', { scope: '/', updateViaCache: 'none' });
      await root.update();
      while (Date.now() < deadline) {
        var worker = root.active;
        if (ownedWorker(worker, '/sw.js') && worker.state === 'activated' &&
            await acknowledge(worker, 'od-privacy-claim') && (service.controller === worker ||
              (ownedWorker(service.controller, '/vr/sw.js') && await acknowledge(service.controller, 'od-vr-retired')))) {
          await caches.delete(RETIRED_CACHE);
          return true;
        }
        await pause();
      }
    } catch (err) {
      // Installing remains optional for a browser with no legacy private worker.
    }
    return safeFallback();
  }

  function registerWorker() {
    // A hung browser update must not start private requests under old control.
    window.odPwaPrivacyReady = Promise.race([
      migrateWorker(),
      new Promise(function (resolve) { window.setTimeout(function () { resolve(safeFallback()); }, PRIVACY_TIMEOUT); }),
    ]).catch(function () { return false; });
  }

  function clearOwnedCaches() {
    if (!window.caches) return;
    caches.keys().then(function (names) {
      return Promise.all(names.filter(function (name) { return name.startsWith('oneirodex-'); })
        .map(function (name) { return caches.delete(name); }));
    }).catch(function () {});
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
        clearOwnedCaches();
        if (!navigator.serviceWorker) return;
        navigator.serviceWorker.getRegistrations().then(function (registrations) {
          registrations.forEach(function (registration) {
            workers(registration).forEach(function (worker) {
              if (ownedWorker(worker, '/sw.js') || ownedWorker(worker, '/vr/sw.js')) {
                worker.postMessage({ type: 'od-clear-caches' });
              }
            });
          });
        }).catch(function () {});
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
