window.AuthXCapture = {
  video(capture, t0, interval, onTick = () => {}, cancelled = () => false) {
    const frames = [];
    let due = 0;
    return new Promise((resolve, reject) => {
      function tick() {
        try {
          const elapsed = performance.now() - t0;
          if (cancelled() || elapsed >= 3000) { resolve(frames); return; }
          if (elapsed >= 0) {
            onTick(elapsed);
            if (elapsed >= due) {
              const image = capture();
              frames.push({ tMs: elapsed, image });
              // No invented/backfilled frames if rendering or encoding is slow.
              due = (Math.floor(elapsed / interval) + 1) * interval;
            }
          }
          setTimeout(tick, 10);
        } catch (error) { reject(error); }
      }
      tick();
    });
  },

  async speech(capture, encodeWav, resample, bufferToBase64) {
    let stream, context, source, node, mute, timeout;
    let cancelled = false;
    const fail = (reason) => Object.assign(new Error(reason), { captureReason: reason });
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      context = new AudioContext();
      await context.resume();
      if (!context.audioWorklet) throw fail('audio_capture_unavailable');
      await context.audioWorklet.addModule('/static/js/audio-capture.js');
      const audioStart = context.currentTime + .1;
      const t0 = performance.now() + 100;
      const startFrame = Math.round(audioStart * context.sampleRate);
      const sampleCount = Math.round(3 * context.sampleRate);
      node = new AudioWorkletNode(context, 'authx-audio-capture', {
        processorOptions: { startFrame, sampleCount }, numberOfInputs: 1,
        numberOfOutputs: 1, channelCount: 1,
      });
      const chunks = [];
      const audioDone = new Promise((resolve, reject) => {
        node.port.onmessage = ({ data }) => {
          if (data.done) resolve();
          else chunks.push(data);
        };
        node.onprocessorerror = () => reject(fail('audio_capture_incomplete'));
        timeout = setTimeout(() => reject(fail('audio_capture_incomplete')), 4100);
      });
      source = context.createMediaStreamSource(stream);
      mute = context.createGain();
      mute.gain.value = 0;
      source.connect(node); node.connect(mute); mute.connect(context.destination);
      const videoDone = this.video(capture, t0, 50, () => {}, () => cancelled);
      const [frames] = await Promise.all([videoDone, audioDone]);
      if (!chunks.length) throw fail('audio_capture_incomplete');
      const firstFrame = chunks[0].startFrame;
      const audioStartMs = (firstFrame - startFrame) * 1000 / context.sampleRate;
      if (audioStartMs < 0 || audioStartMs > 250) throw fail('audio_capture_incomplete');
      let expected = firstFrame;
      for (const chunk of chunks) {
        if (chunk.startFrame !== expected || !chunk.samples.length) throw fail('audio_capture_incomplete');
        expected += chunk.samples.length;
      }
      if (expected !== startFrame + sampleCount) throw fail('audio_capture_incomplete');
      const samples = new Float32Array(expected - firstFrame);
      for (const chunk of chunks) samples.set(chunk.samples, chunk.startFrame - firstFrame);
      if (!samples.every(Number.isFinite)) throw fail('audio_capture_incomplete');
      const audio = resample(samples, context.sampleRate, 16000);
      return { frames, audioStartMs, wav: bufferToBase64(encodeWav(audio, 16000)) };
    } finally {
      cancelled = true;
      clearTimeout(timeout);
      if (node) { node.port.onmessage = null; node.disconnect(); }
      if (source) source.disconnect();
      if (mute) mute.disconnect();
      if (stream) stream.getTracks().forEach((track) => track.stop());
      if (context) await context.close();
    }
  },
};
