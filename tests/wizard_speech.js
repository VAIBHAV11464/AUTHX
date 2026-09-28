// Real wizard click handlers; simulated capture/server verifies word retry flow.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

async function scenario(failures, historical = false) {
  const elements = new Map(), requests = [];
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      hidden: false, value: '', options: [], handlers: {},
      classList: { add() {}, remove() {} },
      addEventListener(event, handler) { this.handlers[event] = handler; },
      replaceChildren() { this.options = []; },
      appendChild(option) { this.options.push(option); },
      async play() {}, videoWidth: 640, videoHeight: 480,
    });
    return elements.get(id);
  }
  let starts = 0;
  const context = {
    window: { AuthXCapture: { async video() { return []; }, async speech() { return { wav: 'fixture', frames: [] }; } } },
    document: { getElementById: element, createElement() { return {}; } },
    localStorage: { getItem() { return 'test-token'; } },
    navigator: { mediaDevices: {
      async getUserMedia() { return { getTracks() { return []; }, getVideoTracks() { return [{ getSettings() { return {}; } }]; } }; },
      async enumerateDevices() { return []; },
    } },
    performance: { now() { return 0; } },
    async fetch(url) {
      requests.push(url);
      let data = { ok: true }, ok = true;
      if (url.endsWith('/start')) data = { ok: true, sessionId: 'session-' + (++starts), word: 'amber', flashStartMs: 2000, captureFrameMs: 50 };
      if (url.endsWith('/speak') && failures.length) { data = failures.shift(); ok = false; }
      if (url.endsWith('/trust')) data = { ok: true, trustScore: 90, riskLabel: 'SAFE' };
      if (url.endsWith('/trust') && historical) { data = { ok: false, reason: 'word_required' }; ok = false; }
      if (url.endsWith('/certificate')) data = { ok: true, certId: 'AX-fixture' };
      return { ok, async json() { return data; } };
    },
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../app/static/js/wizard.js'), 'utf8'), context);
  context.window.AuthXWizard.start({ enrolled: true }, {});
  await element('allow').handlers.click();
  await element('look').handlers.click();
  return { element, requests, get starts() { return starts; } };
}

(async () => {
  const retry = await scenario([
    { ok: false, reason: 'wrong_word', attemptsRemaining: 3 },
    { ok: false, reason: 'speech_model_missing', retryable: true },
  ]);
  await retry.element('speak').handlers.click();
  assert.match(retry.element('wizard-status').textContent, /displayed word.*3 Speak attempt/);
  assert.equal(retry.requests.some(url => /\/(trust|certificate)$/.test(url)), false);
  assert.equal(retry.element('speak').hidden, false);
  await retry.element('speak').handlers.click();
  assert.match(retry.element('wizard-status').textContent, /demo operator/);
  assert.equal(retry.requests.some(url => /\/(trust|certificate)$/.test(url)), false);
  await retry.element('speak').handlers.click();
  assert.equal(retry.requests.filter(url => url.endsWith('/trust')).length, 1);
  assert.equal(retry.requests.filter(url => url.endsWith('/certificate')).length, 1);
  assert.equal(retry.element('speak').hidden, true);

  const exhausted = await scenario([{ ok: false, reason: 'speak_attempts_exhausted', freshSessionRequired: true, attemptsRemaining: 0 }]);
  await exhausted.element('speak').handlers.click();
  assert.match(exhausted.element('wizard-status').textContent, /fresh session with Look/);
  assert.equal(exhausted.element('word-line').hidden, true);
  assert.equal(exhausted.element('speak').hidden, true);
  assert.equal(exhausted.element('look').hidden, false);
  assert.equal(exhausted.requests.some(url => /\/(trust|certificate)$/.test(url)), false);
  await exhausted.element('look').handlers.click();
  assert.equal(exhausted.starts, 2);
  assert.equal(exhausted.element('speak').hidden, false);
  const historical = await scenario([{ ok: false, reason: 'speak_locked' }], true);
  await historical.element('speak').handlers.click();
  assert.equal(historical.element('speak').hidden, true);
  assert.match(historical.element('wizard-status').textContent, /no verified word/);
  assert.equal(historical.requests.some(url => url.endsWith('/certificate')), false);
  console.log('wizard speech ok: retry guidance, setup failures, no premature trust/cert, exhausted fresh session, success');
})().catch(error => { console.error(error); process.exitCode = 1; });
