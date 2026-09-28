// Display uses actual evidence/wizard/faculty scripts and text-only DOM sinks.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    textContent: '', hidden: true, style: {}, handlers: {}, options: [], value: '',
    classList: { add() {}, remove() {} },
    addEventListener(name, handler) { this.handlers[name] = handler; },
    replaceChildren() { this.options = []; }, appendChild(option) { this.options.push(option); },
    async play() {}, videoWidth: 640, videoHeight: 480,
  });
  return elements.get(id);
}
const poison = '<img src=x onerror=alert(1)>';
const context = {
  window: {}, document: { getElementById: element, createElement() { return {}; }, querySelectorAll() { return []; } },
  localStorage: { getItem() { return 'fixture'; } },
  navigator: { mediaDevices: {
    async getUserMedia() { return { getTracks() { return []; }, getVideoTracks() { return [{ getSettings() { return {}; } }]; } }; },
    async enumerateDevices() { return []; },
  } },
  performance: { now() { return 0; } },
};
vm.createContext(context);
function load(name) { vm.runInContext(fs.readFileSync(path.join(__dirname, '../app/static/js/' + name + '.js'), 'utf8'), context); }
load('evidence');
const data = { evidence: { lines: ['Verification: v2', 'Word: ' + poison + ' · confidence 0.90', 'Machine decision: 74 SUSPICIOUS'] } };
context.window.AuthXEvidence.show('verification-evidence', data);
assert.match(element('verification-evidence').textContent, /onerror=alert/);
assert.equal(Object.hasOwn(element('verification-evidence'), 'innerHTML'), false);
assert.equal(element('verification-evidence').hidden, false);
context.window.AuthXEvidence.show('verification-evidence', {});
assert.equal(element('verification-evidence').hidden, true);

(async () => {
  context.window.AuthXCapture = { async video() { return []; }, async speech() { return { frames: [], wav: 'fixture' }; } };
  context.fetch = async (url) => {
    let reply = { ok: true, ...data };
    if (url.endsWith('/start')) reply = { ...reply, sessionId: 'fixture', word: 'amber', flashStartMs: 2000, captureFrameMs: 50 };
    if (url.endsWith('/trust')) reply = { ...reply, trustScore: 74, riskLabel: 'SUSPICIOUS' };
    if (url.endsWith('/certificate')) reply = { ...reply, certId: 'AX-fixture' };
    return { ok: true, async json() { return reply; } };
  };
  load('wizard');
  context.window.AuthXWizard.start({ enrolled: true }, {});
  await element('allow').handlers.click();
  await element('look').handlers.click();
  assert.match(element('verification-evidence').textContent, /Verification: v2/);
  await element('speak').handlers.click();
  assert.match(element('verification-evidence').textContent, /Machine decision: 74 SUSPICIOUS/);
  assert.match(element('verification-evidence').textContent, /confidence 0.90/);
  assert.equal(element('m-cert').textContent, 'AX-fixture');
  assert.equal(Object.hasOwn(element('verification-evidence'), 'innerHTML'), false);

  // Faculty loads after its role check; overriding the stored label preserves the machine summary.
  context.AuthXShell = { requireRole() { return Promise.resolve({ role: 'faculty' }); } };
  context.fetch = async () => ({ ok: true, async json() { return { ...data, username: 'fixture', word: 'amber', riskLabel: 'SAFE', trustScore: 74 }; } });
  load('faculty');
  context.AuthXFaculty = context.window.AuthXFaculty;
  context.window.AuthXFaculty.bindDetail('fixture');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(element('trust-label').textContent, 'SAFE');
  assert.match(element('session-evidence').textContent, /74 SUSPICIOUS/);
  assert.equal(Object.hasOwn(element('session-evidence'), 'innerHTML'), false);
  await element('send-back').handlers.click();
  assert.equal(element('session-evidence').hidden, true);
  console.log('evidence summary display ok: result/faculty, escaped text sink, optional fallback, fresh/reopen reset');
})().catch(error => { console.error(error); process.exitCode = 1; });
