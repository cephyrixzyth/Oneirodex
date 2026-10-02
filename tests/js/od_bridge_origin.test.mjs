/**
 * Regression harness for the WebRetro save bridge's message origin check.
 *
 * od-bridge.js runs inside the same-origin emulator iframe and answers
 * postMessage requests from the shell page (webretro.html): export the save
 * state, import one, pause, reset, press cabinet keys. It used to answer any
 * origin. This pins that only a message whose origin is this page's own origin
 * is acted on, and that a foreign sender gets no reply and causes no side
 * effect.
 *
 * Loads the real script into a vm with just enough of window to register the
 * listener; the emulator globals the bridge reaches for (romName, setIdbItem)
 * are stubs that record calls.
 *
 * Run with: node tests/js/od_bridge_origin.test.mjs
 */

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';

const HERE = path.dirname(url.fileURLToPath(import.meta.url));
const SCRIPT = process.env.OD_BRIDGE_JS || path.resolve(
    HERE, '..', '..', 'oneirodex', 'static', 'vendor', 'webretro', 'od-bridge.js'
);

const ORIGIN = 'https://od.test';

function loadBridge(origin) {
    const listeners = [];
    const idbWrites = [];
    const sandbox = {
        console,
        Uint8Array,
        btoa: (s) => Buffer.from(s, 'binary').toString('base64'),
        atob: (s) => Buffer.from(s, 'base64').toString('binary'),
        setTimeout,
        location: { origin },
        addEventListener(type, handler) { if (type === 'message') { listeners.push(handler); } },
        document: { getElementById: () => null },
        romName: 'test-rom',
        setIdbItem(key, value) { idbWrites.push([key, value]); },
        onbeforeunload: () => 'leave?',
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync(SCRIPT, 'utf8'), sandbox, { filename: SCRIPT });
    assert.equal(listeners.length, 1, 'the bridge registers one message listener');
    return { sandbox, idbWrites, dispatch: listeners[0] };
}

function message(origin, data) {
    const replies = [];
    return {
        event: { origin, data, source: { postMessage: (...args) => replies.push(args) } },
        replies,
    };
}

// --- a same-origin shell is answered ----------------------------------------

{
    const { dispatch } = loadBridge(ORIGIN);
    const { event, replies } = message(ORIGIN, { source: 'oneirodex', type: 'od-ping', reqId: 'r1' });
    dispatch(event);
    assert.equal(replies.length, 1, 'a same-origin ping is answered');
    assert.equal(replies[0][0].source, 'oneirodex-emu');
    assert.equal(replies[0][0].reqId, 'r1');
    assert.equal(replies[0][0].ok, true);
    assert.equal(replies[0][1], ORIGIN, 'the reply is addressed to that origin, not "*"');
}

{
    const { dispatch, idbWrites } = loadBridge(ORIGIN);
    const state = Buffer.from('a state payload that is long enough').toString('base64');
    const { event, replies } = message(ORIGIN, {
        source: 'oneirodex', type: 'od-import-saves', reqId: 'r2', stateB64: state, autoLoad: false,
    });
    dispatch(event);
    assert.equal(replies[0][0].ok, true, 'a same-origin import succeeds');
    assert.equal(idbWrites.length, 1, 'and is written to IndexedDB');
    assert.equal(idbWrites[0][0], 'RetroArch_states_test-rom');
}

{
    const { dispatch, sandbox } = loadBridge(ORIGIN);
    const { event } = message(ORIGIN, { source: 'oneirodex', type: 'od-allow-leave' });
    dispatch(event);
    assert.equal(sandbox.onbeforeunload, null, 'same-origin od-allow-leave clears the leave guard');
}

// --- every other origin is dropped, unanswered, with no side effect ---------

for (const foreign of [
    'https://evil.test',
    'http://od.test',            // scheme differs
    'https://od.test:8443',      // port differs
    'https://sub.od.test',       // subdomain
    'https://od.test.evil.test', // suffix trick
    'null',                      // sandboxed frame / file:
    '',
    undefined,
]) {
    const { dispatch, idbWrites, sandbox } = loadBridge(ORIGIN);
    const label = JSON.stringify(foreign);

    const ping = message(foreign, { source: 'oneirodex', type: 'od-ping', reqId: 'x1' });
    dispatch(ping.event);
    assert.equal(ping.replies.length, 0, `origin ${label}: od-ping must not be answered`);

    const exp = message(foreign, { source: 'oneirodex', type: 'od-export-saves', reqId: 'x2' });
    dispatch(exp.event);
    assert.equal(exp.replies.length, 0, `origin ${label}: od-export-saves must not be answered`);

    const imp = message(foreign, {
        source: 'oneirodex',
        type: 'od-import-saves',
        reqId: 'x3',
        stateB64: Buffer.from('attacker supplied state bytes!!').toString('base64'),
    });
    dispatch(imp.event);
    assert.equal(imp.replies.length, 0, `origin ${label}: od-import-saves must not be answered`);
    assert.equal(idbWrites.length, 0, `origin ${label}: od-import-saves must not write saves`);

    const leave = message(foreign, { source: 'oneirodex', type: 'od-allow-leave' });
    dispatch(leave.event);
    assert.notEqual(sandbox.onbeforeunload, null, `origin ${label}: od-allow-leave must not run`);
}

// --- an opaque page must not match another opaque page ----------------------

{
    const { dispatch, idbWrites } = loadBridge('null');
    const { event, replies } = message('null', {
        source: 'oneirodex', type: 'od-import-saves', reqId: 'n1',
        stateB64: Buffer.from('opaque origin state bytes').toString('base64'),
    });
    dispatch(event);
    assert.equal(replies.length, 0, 'null === null must not count as same-origin');
    assert.equal(idbWrites.length, 0);
}

console.log('od_bridge_origin: all assertions passed');
