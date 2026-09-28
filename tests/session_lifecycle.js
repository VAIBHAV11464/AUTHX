// Task 19: actual browser handlers with deterministic server responses.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function fixture() {
  const elements = new Map(), requests = [], redirects = [];
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      hidden: false, textContent: '', value: '', options: [], handlers: {}, style: {},
      classList: { add() {}, remove() {} },
      addEventListener(event, handler) { this.handlers[event] = handler; },
      replaceChildren() { this.options = []; }, appendChild(item) { this.options.push(item); },
      async play() {}, videoWidth: 640, videoHeight: 480,
    });
    return elements.get(id);
  }
  const context = {
    window: { location: { assign(url) { redirects.push(url); } },
      AuthXCapture: { async video() { return []; }, async speech() { return { wav: 'fixture', frames: [] }; } } },
    document: { getElementById: element, createElement() { return {}; }, querySelectorAll() { return []; } },
    localStorage: { getItem() { return 'fixture'; } },
    navigator: { mediaDevices: {
      async getUserMedia() { return { getTracks() { return []; }, getVideoTracks() { return [{ getSettings() { return {}; } }]; } }; },
      async enumerateDevices() { return []; },
    } },
    AuthXShell: { async requireRole() { return { role: 'faculty' }; } },
    performance: { now() { return 0; } },
  };
  vm.createContext(context);
  function load(name) { vm.runInContext(fs.readFileSync(path.join(__dirname, '../app/static/js/' + name + '.js'), 'utf8'), context); }
  function server(handler) {
    context.fetch = async url => {
      requests.push(url);
      const data = handler(url);
      return { ok: data.ok !== false, async json() { return data; } };
    };
  }
  load('evidence');
  return { context, element, load, server, requests, redirects };
}

(async () => {
  for (const step of ['look', 'speak', 'trust']) {
    const f = fixture();
    f.server(url => {
      if (url.endsWith('/start')) return { ok: true, sessionId: 'old', word: 'amber', flashStartMs: 2000, captureFrameMs: 50 };
      if (url.endsWith('/' + step)) return { ok: false, reason: 'session_expired', freshSessionRequired: true, retryable: false };
      return { ok: true };
    });
    f.load('wizard');
    f.context.window.AuthXWizard.start({ enrolled: true }, {});
    await f.element('allow').handlers.click();
    await f.element('look').handlers.click();
    if (step !== 'look') await f.element('speak').handlers.click();
    assert.match(f.element('wizard-status').textContent, /expired after ten minutes/);
    assert.equal(f.element('speak').hidden, true);
    assert.equal(f.element('word-line').hidden, true);
    assert.equal(f.requests.some(url => url.endsWith('/certificate')), false);
  }
  for (const outcome of [
    { ok: true, newSession: true, sessionId: 'successor' },
    { ok: true, newSession: false, sessionId: 'old' },
    { ok: false, reason: 'session_expired' },
    { ok: false, reason: 'speak_attempts_exhausted' },
    { ok: false, reason: 'speak_in_progress' },
  ]) {
    const f = fixture();
    f.server(url => url.endsWith('/reopen') ? outcome : {
      ok: true, username: 'fixture', word: 'amber', riskLabel: 'SAFE', trustScore: 90, faceScore: 95,
      evidence: { lines: ['Machine decision: 90 SAFE'] },
    });
    f.load('faculty');
    f.context.AuthXFaculty = f.context.window.AuthXFaculty;
    f.context.window.AuthXFaculty.bindDetail('old');
    await new Promise(resolve => setImmediate(resolve));
    await f.element('send-back').handlers.click();
    if (outcome.newSession) {
      assert.deepEqual(f.redirects, ['/faculty/session/successor']);
      assert.equal(f.element('m-face').textContent, 95); // Leave certified history intact while navigating.
    } else if (outcome.ok) {
      assert.equal(f.element('m-face').textContent, '—');
      assert.equal(f.element('session-evidence').hidden, true);
      assert.deepEqual(f.redirects, []);
    } else {
      assert.equal(f.element('m-face').textContent, 95);
      assert.match(f.element('faculty-status').textContent, /expired|Speak attempts|still running/);
      assert.deepEqual(f.redirects, []);
    }
  }
  console.log('session lifecycle UI ok: 3 expiry paths, certified navigation, ordinary clear, 3 reopen failures');
})().catch(error => { console.error(error); process.exitCode = 1; });
