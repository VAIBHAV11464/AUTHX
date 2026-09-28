const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

async function videoCheck(cost) {
  let now = 0;
  const ticks = [];
  const context = { window: {}, performance: { now: () => now },
    setTimeout(callback, delay) { now += delay; queueMicrotask(callback); } };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../app/static/js/capture.js'), 'utf8'), context);
  const frames = await context.window.AuthXCapture.video(() => { now += cost; return 'jpeg'; }, 0, 50, (time) => ticks.push(time));
  assert(frames.length >= (cost ? 25 : 60));
  assert(frames.length <= 60);
  assert(frames.every((frame, i) => frame.tMs < 3000 && (!i || frame.tMs > frames[i - 1].tMs)));
  if (!cost) assert(frames.every((frame, i) => frame.tMs === i * 50));
  else assert(frames.slice(1).every((frame, i) => frame.tMs - frames[i].tMs >= cost));
  assert(ticks.some(time => time >= 2000 && time < 2400));
}

function workletCheck(missing = false) {
  let Capture;
  const messages = [];
  const context = { AudioWorkletProcessor: class { constructor() { this.port = { postMessage(data) { messages.push(data); } }; } },
    currentFrame: 0, registerProcessor(name, type) { Capture = type; } };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../app/static/js/audio-capture.js'), 'utf8'), context);
  const start = 4801, count = 144000;
  const processor = new Capture({ processorOptions: { startFrame: start, sampleCount: count } });
  for (let frame = 0; frame < start + count + 128; frame += 128) {
    context.currentFrame = frame;
    processor.process(missing && frame === 10000 ? [] : [[new Float32Array(128).fill(.1)]]);
  }
  const chunks = messages.filter(message => message.samples);
  assert.equal(chunks[0].startFrame, start);
  assert.equal(chunks.reduce((n, chunk) => n + chunk.samples.length, 0), count);
  assert(chunks.slice(1).every((chunk, i) => chunk.startFrame === chunks[i].startFrame + chunks[i].samples.length));
  assert.equal(messages.filter(message => message.done).length, 1);
}

(async () => {
  await videoCheck(0);
  await videoCheck(80);
  workletCheck();
  console.log('capture timing ok: 20 fps, three seconds, real timestamps under stalls, aligned sample window');
})().catch(error => { console.error(error); process.exitCode = 1; });
