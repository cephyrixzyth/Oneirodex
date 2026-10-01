/**
 * Delegated DOM actions for classic Jinja pages.
 *
 * Inline event handlers (onclick=, onchange=, onsubmit=) are executable script
 * as far as CSP is concerned. After the <script> extract, those attributes were
 * the remaining reason Flask CSP still carried 'unsafe-inline' on script-src.
 * Templates now declare intent on data-* and this listener runs the named
 * global — the same functions the onclick used to call.
 *
 * data-od-click="fn"           → window.fn(optional data-od-arg)
 * data-od-click="reload"       → location.reload()
 * data-od-change="fn"          → window.fn(element.value, optional data-od-arg2)
 * data-od-open="url"           → window.open(url) (does not cancel submit)
 * data-od-confirm="message"    → window.confirm; cancel the click/submit if no
 *
 * Invite copy URLs stay on the button as data-od-arg so a shared file never
 * has to bake a token.
 *
 * Attributes can arrive through injected markup (a folder name, a store string),
 * so none of the above is trusted to name an arbitrary global or URL:
 *   - data-od-click / data-od-change only run the handlers listed below.
 *   - data-od-open only opens same-origin paths and http(s) URLs.
 * A new data-od-click or data-od-change name goes in the matching list in the
 * same change; tests/test_od_dom_actions_allowlist.py fails when they drift.
 */
(function () {
  'use strict';

  function allowlist(names) {
    var set = Object.create(null);
    names.forEach(function (name) {
      set[name] = true;
    });
    return set;
  }

  // Every data-od-click name used by a template or by shipped JS. `reload` is
  // handled separately and is not a global.
  var CLICK_ACTIONS = allowlist([
    'autoPickBest',
    'changePage',
    'clearEntry',
    'closeExtrasModal',
    'closeModal',
    'closeNfoModal',
    'confirmDelete',
    'copyToClipboard',
    'deleteFileType',
    'deleteImage',
    'deleteInvite',
    'deleteSingle',
    'downloadBatch',
    'downloadSingle',
    'editFileType',
    'openExtrasModal',
    'openModal',
    'openNfoModal',
    'plusSlides',
    'refreshHLTB',
    'refreshQueue',
    'retryFailed',
    'saveSettings',
    'showDeleteModal',
    'showExtrasTab',
    'testSettings',
    'toggleIgnoreStatus'
  ]);

  // Every data-od-change name used by a template or by shipped JS.
  var CHANGE_ACTIONS = allowlist(['applyFilters', 'onLibraryChange', 'updateRecipients']);

  function namedFn(name, allowed) {
    if (!name || allowed[name] !== true) return null;
    var fn = window[name];
    return typeof fn === 'function' ? fn : null;
  }

  // Same-origin paths, or an absolute http(s) URL: the "Open IGDB Page" button
  // points at a provider page an admin can set to any http(s) address. Any other
  // scheme (javascript:, data:, vbscript:, blob:) is refused, as is a URL that
  // carries credentials. Parsed with URL, the parser navigation itself uses, so
  // padding or tab tricks inside the scheme do not get past it.
  function openableUrl(raw) {
    if (!raw) return null;
    var parsed;
    try {
      parsed = new URL(raw, window.location.href);
    } catch {
      return null;
    }
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null;
    if (parsed.username || parsed.password) return null;
    return parsed.href;
  }

  function parseArg(raw) {
    if (raw == null || raw === '') return undefined;
    if (/^-?\d+$/.test(raw)) return parseInt(raw, 10);
    return raw;
  }

  function confirmMessage(el) {
    var msg = el.getAttribute('data-od-confirm');
    if (!msg) return true;
    return window.confirm(msg);
  }

  document.addEventListener(
    'click',
    function (event) {
      var confirmEl = event.target.closest('[data-od-confirm]');
      if (confirmEl && confirmEl.tagName !== 'FORM') {
        if (!confirmMessage(confirmEl)) {
          event.preventDefault();
          event.stopPropagation();
          return;
        }
      }

      var openEl = event.target.closest('[data-od-open]');
      if (openEl) {
        var url = openableUrl(openEl.getAttribute('data-od-open'));
        if (url) window.open(url, '_blank', 'noopener,noreferrer');
        return;
      }

      var clickEl = event.target.closest('[data-od-click]');
      if (!clickEl) return;

      var name = clickEl.getAttribute('data-od-click');
      if (name === 'reload') {
        event.preventDefault();
        window.location.reload();
        return;
      }

      var fn = namedFn(name, CLICK_ACTIONS);
      if (!fn) return;
      event.preventDefault();
      var arg = parseArg(clickEl.getAttribute('data-od-arg'));
      var arg2raw = clickEl.getAttribute('data-od-arg2');
      if (arg2raw != null && arg2raw !== '') {
        fn(arg, parseArg(arg2raw));
        return;
      }
      if (arg === undefined) fn(clickEl);
      else fn(arg, clickEl);
    },
    true
  );

  document.addEventListener('change', function (event) {
    var el = event.target.closest('[data-od-change]');
    if (!el) return;
    var fn = namedFn(el.getAttribute('data-od-change'), CHANGE_ACTIONS);
    if (!fn) return;
    var arg2 = el.getAttribute('data-od-arg2');
    if (arg2) fn(el.value, arg2);
    else fn(el.value);
  });

  document.addEventListener(
    'submit',
    function (event) {
      var form = event.target;
      if (!form || form.tagName !== 'FORM') return;
      if (!form.hasAttribute('data-od-confirm')) return;
      if (!confirmMessage(form)) event.preventDefault();
    },
    true
  );
})();
