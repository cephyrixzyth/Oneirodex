/**
 * Member-app service worker — the install path for thin seats (TC-2b) and
 * headsets (Quest PWA-first).
 *
 * Deliberately small, and deliberately paranoid about what it keeps.
 *
 * This is a **multi-member, authenticated** app served from one origin, and a
 * service-worker cache is per-origin, not per-session. Anything cached here
 * would survive a sign-out and could be served to the next person at the same
 * browser profile. So:
 *
 *   - **HTML is never cached.** Every navigation goes to the network. Offline,
 *     the member gets `/offline` — a static page with no library data in it.
 *   - **API responses are never cached.** No `/api/**`, ever.
 *   - Only **immutable-ish static assets** are cached: the built SPA bundles,
 *     vendor libraries, icons and theme files, all of which are versioned by
 *     query string (`?v=`) or content hash, and none of which are member data.
 *   - Cover art is not cached either: it is member-visible library content, and
 *     a household with child accounts should not have one member's shelf
 *     sitting in another's browser storage.
 *
 * The result is an app that installs, opens in its own window, and starts fast
 * — without pretending to be an offline library it cannot honestly be.
 */

const VERSION = 'v2';
const ASSET_CACHE = `oneirodex-assets-${VERSION}`;
const SHELL_CACHE = `oneirodex-shell-${VERSION}`;
const OFFLINE_URL = '/offline';

/**
 * Static roots that hold no member data. Necessary, not sufficient — see
 * `isCacheableAsset`, which also requires the URL to carry a version.
 */
const CACHEABLE_PREFIXES = [
  '/static/dist/',
  '/static/vendor/',
  '/static/icons/',
  '/static/js/',
  '/static/library/themes/',
];
/** Vite content-hashes these filenames, so the path itself is the version. */
const CONTENT_HASHED_PREFIX = '/static/dist/';
/** Never, under any circumstances. */
const NEVER = ['/api/', '/admin/', '/login', '/logout', '/static/library/images/'];

/**
 * Cache-first is only safe for a URL that changes when its bytes change.
 *
 * This used to trust the prefix alone, which was wrong in a way the comment
 * above it did not admit: `/static/vendor/` also holds the EmulatorJS release,
 * and its loader and cores are fetched with **no** version query
 * (`EJS_pathtodata + 'loader.js'`). An installed app that had cached those
 * would keep booting the old cores forever after an operator re-ran
 * `fetch-emulatorjs.sh` — unreachable except by uninstalling the app.
 *
 * So the rule now enforces what it always claimed: content-hashed paths
 * (`/static/dist/`, which Vite hashes), or a `?v=` — which `theme_asset` and
 * the favicon partial both add. Anything else goes to the network, which is
 * the correct answer for a file whose URL cannot tell us it changed.
 */
function isCacheableAsset(url) {
  if (NEVER.some((prefix) => url.pathname.startsWith(prefix))) return false;
  if (!CACHEABLE_PREFIXES.some((prefix) => url.pathname.startsWith(prefix))) return false;
  if (url.pathname.startsWith(CONTENT_HASHED_PREFIX)) return true;
  return url.searchParams.has('v');
}

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((cache) => cache.add(new Request(OFFLINE_URL, { cache: 'reload' })))
      .catch(() => undefined)
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) =>
        Promise.all(
          names
            .filter((name) => name.startsWith('oneirodex-') && !name.endsWith(VERSION))
            .map((name) => caches.delete(name)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Navigations: network only, with a data-free offline page as the fallback.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(() =>
        caches.match(OFFLINE_URL).then((cached) => cached || Response.error()),
      ),
    );
    return;
  }

  if (!isCacheableAsset(url)) return;

  // Assets: cache first (they are versioned, so a change is a new URL), then
  // network, and only store a clean 200 from this origin.
  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) return cached;
      return fetch(request).then((response) => {
        if (response && response.status === 200 && response.type === 'basic') {
          const copy = response.clone();
          caches.open(ASSET_CACHE).then((cache) => cache.put(request, copy));
        }
        return response;
      });
    }),
  );
});

/** A sign-out tells the worker to drop everything it holds. */
self.addEventListener('message', (event) => {
  if (!event.data || event.data.type !== 'od-clear-caches') return;
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(names.filter((name) => name.startsWith('oneirodex-')).map((n) => caches.delete(n))),
    ),
  );
});
