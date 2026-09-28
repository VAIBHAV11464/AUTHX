// AudioWorklet records the actual input sample clock; it never plays the mic.
class AuthXAudioCapture extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.start = options.processorOptions.startFrame;
    this.end = this.start + options.processorOptions.sampleCount;
    this.done = false;
  }
  process(inputs) {
    if (this.done) return false;
    const channel = inputs[0] && inputs[0][0];
    if (channel) {
      const left = Math.max(0, this.start - currentFrame);
      const right = Math.min(channel.length, this.end - currentFrame);
      if (right > left) {
        const samples = channel.slice(left, right);
        this.port.postMessage({ startFrame: currentFrame + left, samples }, [samples.buffer]);
      }
    }
    if (currentFrame + 128 >= this.end) {
      this.done = true;
      this.port.postMessage({ done: true });
      return false;
    }
    return true;
  }
}
registerProcessor('authx-audio-capture', AuthXAudioCapture);
