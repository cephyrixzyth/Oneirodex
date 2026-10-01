/**
 * Regression harness for static/js/od_dom_actions.js.
 *
 * The delegated listener used to run window[data-od-click] for whatever name
 * the attribute spelled, and window.open(data-od-open) for whatever URL it
 * held. Both attributes can be reached by injected markup (a folder name, a
 * store string), so this pins the two restrictions:
 *
 *   - data-od-click / data-od-change only run handlers on the allowlist.
 *   - data-od-open only opens same-origin paths and http(s) URLs, without an
 *     opener.
 *
 * Runs on a hand-rolled micro-DOM (no jsdom dependency): just enough of
 * document/closest/getAttribute for the delegated listeners.
 *
 * Run with: node tests/js/od_dom_actions.test.mjs
 */

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';

const HERE = path.dirname(url.fileURLToPath(import.meta.url));
const SCRIPT = process.env.OD_DOM_ACTIONS_JS || path.resolve(
    HERE, '..', '..', 'oneirodex', 'static', 'js', 'od_dom_actions.js'
);

class Element {
    constructor(tagName, attributes = {}, parent = null) {
        this.tagName = tagName.toUpperCase();
        this._attributes = attributes;
        this.parentNode = parent;
        this.value = '';
    }
    getAttribute(name) { return name in this._attributes ? this._attributes[name] : null; }
    hasAttribute(name) { return name in this._attributes; }
    closest(selector) {
        const attr = /^\[([\w-]+)\]$/.exec(selector)[1];
        for (let node = this; node; node = node.parentNode) {
            if (node.hasAttribute(attr)) { return node; }
        }
        return null;
    }
}

const listeners = {};
const calls = [];
const opened = [];
let reloads = 0;

const sandbox = {
    URL,
    console,
    document: {
        addEventListener(type, handler) { (listeners[type] = listeners[type] || []).push(handler); },
    },
    location: { href: 'https://od.test/admin/games', reload() { reloads += 1; } },
    open(...args) { opened.push(args); return null; },
    confirm() { return true; },
    // Handlers that exist on the page. Only some of them are on the allowlist.
    deleteImage(...args) { calls.push(['deleteImage', ...args]); },
    plusSlides(...args) { calls.push(['plusSlides', ...args]); },
    downloadBatch(...args) { calls.push(['downloadBatch', ...args]); },
    applyFilters(...args) { calls.push(['applyFilters', ...args]); },
    onLibraryChange(...args) { calls.push(['onLibraryChange', ...args]); },
    evilHandler(...args) { calls.push(['evilHandler', ...args]); },
    eval: (...args) => { calls.push(['eval', ...args]); },
    alert: (...args) => { calls.push(['alert', ...args]); },
};
sandbox.window = sandbox;
sandbox.window.location = sandbox.location;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(SCRIPT, 'utf8'), sandbox, { filename: SCRIPT });

function fire(type, target) {
    const event = {
        type,
        target,
        defaultPrevented: false,
        preventDefault() { this.defaultPrevented = true; },
        stopPropagation() {},
    };
    (listeners[type] || []).forEach((handler) => handler(event));
    return event;
}

function click(attributes) {
    calls.length = 0;
    opened.length = 0;
    return fire('click', new Element('button', attributes));
}

function change(attributes, value = 'v') {
    calls.length = 0;
    const el = new Element('select', attributes);
    el.value = value;
    return fire('change', el);
}

// --- data-od-click: allowlisted handlers still work ------------------------

let event = click({ 'data-od-click': 'deleteImage', 'data-od-arg': '42' });
assert.equal(calls.length, 1, 'an allowlisted handler runs');
assert.deepEqual(calls[0].slice(0, 2), ['deleteImage', 42], 'numeric data-od-arg is parsed');
assert.ok(event.defaultPrevented, 'a handled click is cancelled');

click({ 'data-od-click': 'plusSlides', 'data-od-arg': '-1' });
assert.deepEqual(calls[0].slice(0, 2), ['plusSlides', -1], 'negative numeric arg is parsed');

click({ 'data-od-click': 'downloadBatch', 'data-od-arg': '10' });
assert.deepEqual(calls[0].slice(0, 2), ['downloadBatch', 10]);

click({ 'data-od-click': 'reload' });
assert.equal(reloads, 1, 'reload is still a built-in action');

// --- data-od-click: anything else is ignored -------------------------------

for (const name of [
    'evilHandler',      // a real global, just not allowlisted
    'eval',
    'alert',
    'open',
    'confirm',
    'constructor',
    '__proto__',
    'toString',
    'hasOwnProperty',
    'window',
    'location.assign',
    'document.write',
    ' deleteImage',
    'deleteImage ',
    'DeleteImage',
]) {
    event = click({ 'data-od-click': name, 'data-od-arg': 'alert(document.domain)' });
    assert.equal(calls.length, 0, `data-od-click="${name}" must not run anything`);
    assert.equal(event.defaultPrevented, false, `data-od-click="${name}" must not swallow the click`);
    assert.equal(opened.length, 0, `data-od-click="${name}" must not open anything`);
}

// --- data-od-change --------------------------------------------------------

change({ 'data-od-change': 'onLibraryChange', 'data-od-arg2': 'auto' }, 'lib-1');
assert.deepEqual(calls, [['onLibraryChange', 'lib-1', 'auto']], 'allowlisted change handler runs');

change({ 'data-od-change': 'applyFilters' }, 'x');
assert.deepEqual(calls, [['applyFilters', 'x']]);

for (const name of ['evilHandler', 'eval', 'alert', 'plusSlides', 'constructor', '__proto__']) {
    change({ 'data-od-change': name });
    assert.equal(calls.length, 0, `data-od-change="${name}" must not run anything`);
}

// data-od-click names are not data-od-change names and vice versa.
change({ 'data-od-change': 'deleteImage' });
assert.equal(calls.length, 0, 'a click-only handler is not runnable from a change event');
click({ 'data-od-click': 'applyFilters' });
assert.equal(calls.length, 0, 'a change-only handler is not runnable from a click');

// --- data-od-open ----------------------------------------------------------

click({ 'data-od-open': 'https://www.igdb.com/games/some-game' });
assert.deepEqual(
    opened,
    [['https://www.igdb.com/games/some-game', '_blank', 'noopener,noreferrer']],
    'an http(s) provider page opens, without an opener'
);

click({ 'data-od-open': '/library/game/abc' });
assert.deepEqual(
    opened,
    [['https://od.test/library/game/abc', '_blank', 'noopener,noreferrer']],
    'a same-origin path resolves against the page and opens'
);

for (const hostile of [
    'javascript:alert(document.domain)',
    '  JavaScript:alert(1)',
    'java\tscript:alert(1)',
    'java\nscript:alert(1)',
    'data:text/html,<script>alert(1)</script>',
    'vbscript:msgbox(1)',
    'blob:https://od.test/0b2f',
    'file:///etc/passwd',
    'ms-msdt:/id PCWDiagnostic',
    'steam://openurl/https://example.test',
    'https://user:secret@evil.test/',
    'http://igdb.com@evil.test:pw@host/',
]) {
    click({ 'data-od-open': hostile });
    assert.equal(opened.length, 0, `data-od-open=${JSON.stringify(hostile)} must not open`);
}

click({ 'data-od-open': '' });
assert.equal(opened.length, 0, 'an empty data-od-open opens nothing');

console.log('od_dom_actions: all assertions passed');
