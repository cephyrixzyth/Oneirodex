/**
 * Regression harness for filesystem and metadata strings reaching innerHTML.
 *
 * Folder names, game paths, proposal candidates, local/remote version strings
 * and request errors are data from the disk or from a store API. The classic
 * admin/member scripts below used to interpolate them straight into markup, so
 * a folder named `<img src=x onerror=...>` ran script in the admin's session.
 * Each scenario feeds a hostile string through the real script and asserts it
 * comes out as text, and that a normal name renders exactly as before.
 *
 * Covers:
 *   static/js/od_admin_library_tools.js           proposals, rename search, rename plan
 *   setup/default_theme/js/game_details.js        freshness panel
 *   setup/default_theme/js/admin_manage_scanjobs.js  fetchFolders (folder browser)
 *
 * Runs on hand-rolled stubs (no jsdom, no jQuery): an element that records the
 * markup assigned to it, and a minimal jQuery that tells .text() from .html().
 *
 * Run with: node tests/js/admin_html_injection.test.mjs
 */

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';

const HERE = path.dirname(url.fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..', '..', 'oneirodex');
// Overridable so the harness can be pointed at an older revision of a file to
// confirm it really does catch the bug it is guarding against.
const LIBRARY_TOOLS = process.env.OD_LIBRARY_TOOLS_JS || path.join(ROOT, 'static', 'js', 'od_admin_library_tools.js');
const GAME_DETAILS = process.env.OD_GAME_DETAILS_JS || path.join(ROOT, 'setup', 'default_theme', 'js', 'game_details.js');
const SCANJOBS = process.env.OD_SCANJOBS_JS || path.join(ROOT, 'setup', 'default_theme', 'js', 'admin_manage_scanjobs.js');

const PAYLOADS = [
    '<img src=x onerror=alert(1)>',
    '"><script>alert(2)</script>',
    '<svg onload=alert(3)>',
    "'><b>x</b>",
];

/** Fails when a payload tag reached the markup unescaped. */
function assertInert(markup, label) {
    for (const needle of ['<img', '<script', '<svg', '<b>']) {
        assert.ok(!markup.includes(needle), `${label}: raw "${needle}" reached markup:\n${markup}`);
    }
}

function decodeEntities(text) {
    return text
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&quot;/g, '"')
        .replace(/&#39;/g, "'")
        .replace(/&amp;/g, '&');
}

const tick = () => new Promise((resolve) => setImmediate(resolve));
async function settle() { for (let i = 0; i < 5; i += 1) { await tick(); } }

function stubElement(id) {
    const listeners = {};
    return {
        id,
        value: '',
        checked: false,
        disabled: false,
        hidden: false,
        textContent: '',
        dataset: {},
        _html: '',
        _listeners: listeners,
        set innerHTML(value) { this._html = String(value); },
        get innerHTML() { return this._html; },
        addEventListener(type, handler) { (listeners[type] = listeners[type] || []).push(handler); },
        async fire(type, event = {}) {
            for (const handler of listeners[type] || []) { await handler(event); }
        },
    };
}

function jsonResponse(body, { ok = true, status = 200 } = {}) {
    return { ok, status, statusText: 'x', json: async () => body };
}

// ---------------------------------------------------------------------------
// od_admin_library_tools.js
// ---------------------------------------------------------------------------

function loadLibraryTools(fetchImpl) {
    const elements = {};
    const document = {
        getElementById(id) { return (elements[id] = elements[id] || stubElement(id)); },
        querySelectorAll() { return []; },
    };
    const sandbox = { document, fetch: fetchImpl, confirm: () => true, console, parseInt, JSON, encodeURIComponent };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync(LIBRARY_TOOLS, 'utf8'), sandbox, { filename: LIBRARY_TOOLS });
    return elements;
}

// Proposal sidecars: hostile name, path, uuid and candidate.
for (const payload of PAYLOADS) {
    const els = loadLibraryTools(async () => jsonResponse({
        proposals: [{
            game_name: payload,
            path: payload,
            game_uuid: payload,
            proposal: { candidates: [{ name: payload, score: payload }] },
        }],
    }));
    await els.loadProposalsBtn.fire('click');
    const markup = els.proposalsList.innerHTML;
    assertInert(markup, 'proposal sidecar');
    assert.ok(markup.includes(`<strong>${payload.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;')}</strong>`),
        'the hostile name is shown as text');
    // The attribute must not be breakable either.
    assert.match(markup, /data-path="[^"]*"/);
    assert.equal(decodeEntities(/data-path="([^"]*)"/.exec(markup)[1]), payload);
}

// Normal sidecar renders exactly as before.
{
    const els = loadLibraryTools(async () => jsonResponse({
        proposals: [{
            game_name: 'Half-Life 2',
            path: '/games/Half-Life 2',
            game_uuid: 'abc-123',
            proposal: { candidates: [{ name: 'Half-Life 2', score: 0.93 }] },
        }],
    }));
    await els.loadProposalsBtn.fire('click');
    const markup = els.proposalsList.innerHTML;
    assert.ok(markup.includes('data-path="/games/Half-Life 2"'));
    assert.ok(markup.includes('<strong>Half-Life 2</strong> <code>abc-123</code>'));
    assert.ok(markup.includes('<code>/games/Half-Life 2</code><br>Half-Life 2 (0.93)'));
}

// scan_roots failing falls back to the plain scan and shows the error text.
{
    let call = 0;
    const els = loadLibraryTools(async () => {
        call += 1;
        if (call === 1) { throw new Error(PAYLOADS[0]); }
        return jsonResponse({ proposals: [] });
    });
    await els.loadProposalsBtn.fire('click');
    assertInert(els.proposalsList.innerHTML, 'proposal scan error');
    assert.ok(els.proposalsList.innerHTML.includes('&lt;img src=x onerror=alert(1)&gt;'));
}

// Rename search hits: name, uuid and path land in both text and attributes.
for (const payload of PAYLOADS) {
    const name = `Tom "${payload}" & Jerry`;
    const els = loadLibraryTools(async () => jsonResponse({
        games: [{ uuid: payload, name, full_disk_path: payload }],
    }));
    els.renameSearch.value = 'tom';
    await els.renameSearchBtn.fire('click');
    await settle();
    const markup = els.renameSearchHits.innerHTML;
    assertInert(markup, 'rename search hit');
    assert.equal(decodeEntities(/data-name="([^"]*)"/.exec(markup)[1]), name,
        'data-name round-trips through the attribute');
    assert.equal(decodeEntities(/data-uuid="([^"]*)"/.exec(markup)[1]), payload);
}

{
    const els = loadLibraryTools(async () => jsonResponse({
        games: [{ uuid: 'u-1', name: 'Doom', full_disk_path: '/games/Doom' }],
    }));
    els.renameSearch.value = 'doom';
    await els.renameSearchBtn.fire('click');
    await settle();
    const markup = els.renameSearchHits.innerHTML;
    assert.ok(markup.includes('data-uuid="u-1" data-name="Doom"'));
    assert.ok(markup.includes('<strong>Doom</strong><br><code class="small">u-1</code>'));
    assert.ok(markup.includes('<br><span class="small text-muted">/games/Doom</span>'));
}

{
    const els = loadLibraryTools(async () => { throw new Error(PAYLOADS[0]); });
    els.renameSearch.value = 'q';
    await els.renameSearchBtn.fire('click');
    await settle();
    assertInert(els.renameSearchHits.innerHTML, 'rename search error');
}

// Rename plan: kind and both paths.
for (const payload of PAYLOADS) {
    const els = loadLibraryTools(async () => jsonResponse({
        plan: [{ kind: payload, from_path: payload, to_path: payload }],
    }));
    await els.renamePreviewBtn.fire('click');
    assertInert(els.renamePlan.innerHTML, 'rename plan');
}

{
    const els = loadLibraryTools(async () => jsonResponse({
        plan: [{ kind: 'rename_root', from_path: '/a/Old', to_path: '/a/New' }],
    }));
    await els.renamePreviewBtn.fire('click');
    assert.ok(els.renamePlan.innerHTML.includes('<code>rename_root</code>: /a/Old → /a/New</label>'));
}

// ---------------------------------------------------------------------------
// game_details.js: freshness panel
// ---------------------------------------------------------------------------

async function runFreshness(responseOrError) {
    const elements = {
        'game-freshness-panel': Object.assign(stubElement('game-freshness-panel'), { dataset: { gameUuid: 'g-1' } }),
        'freshness-check-btn': stubElement('freshness-check-btn'),
        'freshness-status-line': stubElement('freshness-status-line'),
        'freshness-details': stubElement('freshness-details'),
    };
    const domReady = [];
    const document = {
        addEventListener(type, handler) { if (type === 'DOMContentLoaded') { domReady.push(handler); } },
        getElementById(id) { return elements[id] || null; },
    };
    const fetchImpl = async () => {
        if (responseOrError instanceof Error) { throw responseOrError; }
        return responseOrError;
    };
    const sandbox = { document, fetch: fetchImpl, console, JSON, window: null };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync(GAME_DETAILS, 'utf8'), sandbox, { filename: GAME_DETAILS });
    const init = domReady.find((fn) => fn.name === 'initFreshnessPanel');
    assert.ok(init, 'the freshness panel registers its DOMContentLoaded handler');
    init();
    await elements['freshness-check-btn'].fire('click');
    return elements['freshness-status-line'].innerHTML;
}

for (const payload of PAYLOADS) {
    assertInert(await runFreshness(jsonResponse({
        status: payload,
        confidence: payload,
        local_version: payload,
        remote_version_summary: payload,
        checked_at: payload,
    })), 'freshness result');
    assertInert(await runFreshness(jsonResponse({ error: payload }, { ok: false, status: 500 })), 'freshness error');
    assertInert(await runFreshness(new Error(payload)), 'freshness thrown error');
}

assert.equal(
    await runFreshness(jsonResponse({
        status: 'outdated',
        confidence: 'high',
        local_version: '1.2.3',
        remote_version_summary: 'remote 1.4.0',
        checked_at: '2026-09-30 10:00',
    })),
    '<strong>outdated</strong> (high) — local 1.2.3 — remote 1.4.0 <span class="text-muted"> · checked 2026-09-30 10:00</span>',
    'a normal freshness line renders exactly as before'
);
assert.equal(
    await runFreshness(jsonResponse({ error: 'Store unreachable' }, { ok: false, status: 502 })),
    '<span class="text-danger">Store unreachable</span>'
);

// ---------------------------------------------------------------------------
// admin_manage_scanjobs.js: fetchFolders
// ---------------------------------------------------------------------------

function extractTopLevelFunction(source, name) {
    const start = source.search(new RegExp(`^function ${name}\\(`, 'm'));
    assert.ok(start >= 0, `function ${name} exists`);
    const end = source.indexOf('\n}', start);
    assert.ok(end > start, `function ${name} closes`);
    return source.slice(start, end + 2);
}

function makeJqueryEl(selector) {
    const el = {
        selector,
        htmlSet: false,
        textValue: null,
        htmlValue: null,
        children: [],
        classes: new Set(),
        attrs: {},
        text(value) { this.textValue = String(value); this.htmlSet = false; return this; },
        html(value) { this.htmlValue = String(value); this.htmlSet = true; return this; },
        append(child) { this.children.push(child); return this; },
        empty() { this.children = []; return this; },
        addClass(name) { String(name).split(/\s+/).forEach((c) => c && this.classes.add(c)); return this; },
        attr(key, value) { this.attrs[key] = value; return this; },
        css() { return this; },
        show() { return this; },
        hide() { return this; },
        click() { return this; },
        val() { return this; },
        data() { return ''; },
    };
    const classMatch = /^<div class="([^"]+)">$/.exec(selector);
    if (classMatch) { el.addClass(classMatch[1]); }
    const spanMatch = /^<span class="([^"]+)">$/.exec(selector);
    if (spanMatch) { el.addClass(spanMatch[1]); }
    return el;
}

function browseFolders(items, extra = {}) {
    const source = fs.readFileSync(SCANJOBS, 'utf8');
    const registry = {};
    let ajax = null;
    function $(arg) {
        if (typeof arg === 'string') {
            if (arg.startsWith('<')) { return makeJqueryEl(arg); }
            return (registry[arg] = registry[arg] || makeJqueryEl(arg));
        }
        return arg;
    }
    $.ajax = (options) => { ajax = options; };
    const sandbox = { $, console: { log() {} }, fileIcons: { default: 'fa-file' }, window: null };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(
        [
            extractTopLevelFunction(source, 'formatFileSize'),
            extractTopLevelFunction(source, 'fetchFolders'),
        ].join('\n'),
        sandbox,
        { filename: SCANJOBS }
    );
    sandbox.fetchFolders('/games/', '#contents', '#spinner', '#up', '#input', 'currentPath');
    assert.ok(ajax, 'fetchFolders issues its listing request');
    ajax.success({ items, ...extra });
    return registry['#contents'].children;
}

function describeEl(el) {
    return { text: el.textValue, html: el.htmlSet ? el.htmlValue : null, classes: [...el.classes] };
}

for (const payload of PAYLOADS) {
    const children = browseFolders(
        [
            { name: payload, isDir: true },
            { name: payload, isDir: false, ext: '.exe', size: 2048 },
        ],
        { hasErrors: true, skippedItems: payload }
    );
    assert.equal(children.length, 3, 'warning, folder and file are all listed');
    for (const child of children) {
        assert.equal(child.htmlSet, false, `no .html() sink for ${JSON.stringify(payload)}`);
    }
    const [warning, folder, file] = children;
    assert.ok(warning.textValue.includes(payload), 'the warning count is text');
    assert.equal(folder.textValue, `📁 ${payload}`, 'folder name is text');
    assert.equal(file.textValue, payload, 'file name is text');
    assert.equal(file.attrs.title, `${payload} - 2 KB`);
    assert.equal(file.children.length, 1, 'the size badge is appended as an element');
    assert.equal(file.children[0].textValue, '(2 KB)');
    assert.ok(file.children[0].classes.has('file-size'));
}

// A normal folder and file list exactly as before.
{
    const [warning, folder, file] = browseFolders(
        [
            { name: 'Half-Life 2', isDir: true },
            { name: 'setup.exe', isDir: false, ext: '.exe', size: 1536 },
        ],
        { hasErrors: true, skippedItems: 3 }
    );
    assert.equal(warning.textValue, '⚠ Some items (3) could not be accessed and were skipped.');
    assert.deepEqual(describeEl(folder), { text: '📁 Half-Life 2', html: null, classes: ['folder-item'] });
    assert.equal(folder.attrs['data-path'], '/games/Half-Life 2/');
    assert.deepEqual(describeEl(file), { text: 'setup.exe', html: null, classes: ['file-item'] });
    assert.equal(file.attrs.title, 'setup.exe - 1.5 KB');
    assert.equal(file.children[0].textValue, '(1.5 KB)');
}

console.log('admin_html_injection: all assertions passed');
