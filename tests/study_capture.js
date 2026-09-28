// Execute the actual rendered collector bootstrap/consent/device-stop scripts.
// Simulated DOM/device policy only; no real hardware or volunteers.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const { webcrypto } = require('crypto');
const scripts = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const elements = new Map();
for (const name of ['wizard', 'live', 'camera', 'study-agree', 'study-end', 'study-note']) {
  elements.set(name, { hidden: false, disabled: false, textContent: '', srcObject: null });
}
let deviceCalls = 0, stopped = 0, allowed = false, initialized = 0;
const calls = [];
const track = {readyState: 'live', getSettings: () => ({deviceId: 'controlled-camera'}), stop: () => {stopped++;}};
const stream = {getVideoTracks: () => [track], getTracks: () => [track]};
const context = {
  document: { getElementById: name => elements.get(name) },
  navigator: { mediaDevices: {getUserMedia: async () => {deviceCalls++; return stream;}} },
  crypto: webcrypto, TextEncoder, Uint8Array, Set, JSON,
  fetch: async (url, options) => {calls.push([url, options]); return {ok: allowed};},
};
context.window = context;
vm.createContext(context);
vm.runInContext(scripts[0], context);
// The product wizard starts only once the study promise resolves.
context.AuthXShell.requireRole().then(me => {
  assert.equal(me.role, 'student'); initialized++; elements.get('wizard').hidden = false;
});
vm.runInContext(scripts[scripts.length-1], context);
(async () => {
  assert.equal(deviceCalls, 0);
  assert.equal(elements.get('wizard').hidden, true);
  await elements.get('study-agree').onclick();
  assert.equal(initialized, 0);
  assert.equal(deviceCalls, 0);
  allowed = true;
  await elements.get('study-agree').onclick();
  await Promise.resolve();
  assert.equal(initialized, 1);
  assert.equal(deviceCalls, 0);
  await context.navigator.mediaDevices.getUserMedia({video: true});
  assert.equal(deviceCalls, 1);
  assert(elements.get('study-note').textContent.startsWith('Active camera key: '));
  const before = calls.length;
  elements.get('live').srcObject = stream;
  elements.get('camera').disabled = true;
  await elements.get('study-end').onclick();
  assert.equal(calls.length, before);
  assert.equal(stopped, 0);
  elements.get('camera').disabled = false;
  await context.fetch('/api/face/enroll', {method: 'POST', body: '{}'});
  assert.equal(calls[calls.length-2][0], '/study/device');
  assert.equal(calls[calls.length-1][0], '/api/face/enroll');
  const headers = calls[calls.length-1][1].headers;
  assert.equal(headers.Authorization, 'Bearer CONTROLLED_TEST_TOKEN');
  assert.equal(headers['X-AuthX-Study'], 'CONTROLLED_TEST_KEY');
  await elements.get('study-end').onclick();
  assert.equal(stopped, 1);
  assert.equal(elements.get('wizard').hidden, true);
  assert.equal(calls[calls.length-1][0], '/study/end');
  console.log('Collector consent/device simulation passed: pending consent, explicit device action, camera check, busy guard, stop and end.');
})().catch(error => {console.error(error); process.exit(1);});
