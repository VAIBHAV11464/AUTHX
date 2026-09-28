// Exercise the real Enroll click handler with a simulated camera and server.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

async function check(samples, fail = false) {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      hidden: false, value: '', options: [], handlers: {},
      classList: { add() {}, remove() {} },
      addEventListener(event, handler) { this.handlers[event] = handler; },
      replaceChildren() { this.options = []; },
      appendChild(option) { this.options.push(option); },
      videoWidth: 640, videoHeight: 480, async play() {},
    });
    return elements.get(id);
  }
  let captures = 0;
  const waits = [], requests = [];
  const context = {
    window: {},
    document: {
      getElementById: element,
      createElement(type) {
        if (type !== 'canvas') return {};
        return { getContext() { return { drawImage() {} }; },
          toDataURL() { captures += 1; return 'data:image/jpeg;base64,' + captures; } };
      },
    },
    localStorage: { getItem() { return 'test-token'; } },
    navigator: { mediaDevices: {
      async getUserMedia() { return { getTracks() { return []; }, getVideoTracks() { return [{ getSettings() { return {}; } }]; } }; },
      async enumerateDevices() { return []; },
    } },
    setTimeout(callback, delay) { waits.push(delay); queueMicrotask(callback); },
    async fetch(url, options) {
      requests.push({ url, body: JSON.parse(options.body) });
      return { ok: !fail, async json() { return fail
        ? { ok: false, reason: 'inconsistent_enrollment' } : { ok: true, enrolled: true }; } };
    },
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../app/static/js/wizard.js'), 'utf8'), context);
  context.window.AuthXWizard.start({ enrolled: fail }, { enrollmentSamples: samples });
  await element('allow').handlers.click();
  const button = element(fail ? 'enroll-again' : 'enroll');
  await Promise.all([button.handlers.click(), button.handlers.click()]);
  assert.equal(requests.length, 1, 'busy state prevents duplicate enrollment');
  assert.equal(requests[0].url, '/api/face/enroll');
  assert.equal(captures, samples);
  if (samples === 5) {
    assert.equal(requests[0].body.images.length, 5);
    assert.deepEqual(waits, [200, 200, 200, 200]);
  } else {
    assert.equal(typeof requests[0].body.image, 'string');
    assert.equal(waits.length, 0);
  }
  assert.equal(element('look').hidden, false, 'successful enrollment or preserved old enrollment can continue');
  if (fail) assert.match(element('wizard-status').textContent, /consistent face/);
}

(async () => {
  await check(1);
  await check(5);
  await check(5, true);
  console.log('wizard enrollment ok: legacy, five-image v2, failed reenrollment, duplicate-click guard');
})().catch((error) => { console.error(error); process.exitCode = 1; });
