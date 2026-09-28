window.AuthXWizard = {
  start(me, settings) {
    const root = document.getElementById('wizard');
    const camera = document.getElementById('camera');
    const preview = document.getElementById('preview');
    const live = document.getElementById('live');
    const prompt = document.getElementById('prompt');
    const allow = document.getElementById('allow');
    const enroll = document.getElementById('enroll');
    const enrollAgain = document.getElementById('enroll-again');
    const look = document.getElementById('look');
    const speak = document.getElementById('speak');
    const wordLine = document.getElementById('word-line');
    const status = document.getElementById('wizard-status');
    const metrics = document.getElementById('look-metrics');
    const speakMetrics = document.getElementById('speak-metrics');
    const longSide = settings.longSide || 640;
    const jpegQuality = settings.jpegQuality || 0.7;
    const flashMs = settings.flashMs || 400;
    const sampleRate = settings.sampleRate || 16000;
    const clipMs = 3000;
    const frameEvery = 200;
    const enrollmentSamples = settings.enrollmentSamples === 5 ? 5 : 1;
    let stream = null;
    let enrolled = !!me.enrolled;
    let busy = false;
    let sessionId = null;
    let challengeWord = '';
    let captureFrameMs = null;

    function token() {
      return localStorage.getItem('authx_token');
    }

    function showStatus(text) {
      status.hidden = !text;
      status.textContent = text || '';
    }

    function setButtons() {
      const ready = !!stream && !busy;
      enroll.hidden = !ready || enrolled;
      enrollAgain.hidden = !ready || !enrolled;
      look.hidden = !ready || !enrolled;
      speak.hidden = !ready || !sessionId;
      camera.disabled = !stream || busy;
    }

    function cameraName(device, index) {
      const label = device.label || ('Camera ' + (index + 1));
      const lower = label.toLowerCase();
      if (lower.includes('usb') || lower.includes('external')) return 'USB webcam — ' + label;
      if (
        lower.includes('integrated')
        || lower.includes('built-in')
        || lower.includes('builtin')
        || lower.includes('facetime')
        || lower.includes('laptop')
      ) {
        return 'Laptop camera — ' + label;
      }
      return label;
    }

    async function openCamera(deviceId) {
      if (stream) stream.getTracks().forEach((track) => track.stop());
      const video = { width: { ideal: longSide }, height: { ideal: 480 } };
      if (deviceId) video.deviceId = { exact: deviceId };
      stream = await navigator.mediaDevices.getUserMedia({ video, audio: false });
      live.srcObject = stream;
      await live.play();
    }

    async function fillCameras() {
      const devices = (await navigator.mediaDevices.enumerateDevices()).filter(
        (device) => device.kind === 'videoinput',
      );
      camera.replaceChildren();
      devices.forEach((device, index) => {
        const option = document.createElement('option');
        option.value = device.deviceId;
        option.textContent = cameraName(device, index);
        camera.appendChild(option);
      });
      const active = stream && stream.getVideoTracks()[0].getSettings().deviceId;
      if (active) camera.value = active;
      if (!camera.options.length) {
        const option = document.createElement('option');
        option.textContent = 'No camera found';
        camera.appendChild(option);
      }
    }

    function capture() {
      const sourceWidth = live.videoWidth || 640;
      const sourceHeight = live.videoHeight || 480;
      const scale = Math.min(1, longSide / Math.max(sourceWidth, sourceHeight));
      const canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.round(sourceWidth * scale));
      canvas.height = Math.max(1, Math.round(sourceHeight * scale));
      canvas.getContext('2d').drawImage(live, 0, 0, canvas.width, canvas.height);
      return canvas.toDataURL('image/jpeg', jpegQuality);
    }

    async function postJson(url, body) {
      const res = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: 'Bearer ' + token(),
        },
        body: JSON.stringify(body || {}),
      });
      let data = {};
      try {
        data = await res.json();
      } catch (err) {
        data = {};
      }
      return { res, data };
    }

    function captureMessage(reason) {
      const messages = {
        multiple_faces: 'Keep only one person in the camera view, then try again.',
        face_too_small: 'Move closer so your face fills more of the camera view.',
        face_cut_off: 'Center your whole face in the camera view, then try again.',
        face_too_dark: 'Add light in front of your face, then try again.',
        face_too_bright: 'Reduce the light on your face, then try again.',
        uneven_face_lighting: 'Use even light in front of your face and avoid backlighting.',
        face_blurry: 'Hold still and let the camera focus, then try again.',
        too_few_usable_face_frames: 'Keep your face visible for the full recording, then try again.',
        bad_image: 'The camera image was unreadable. Capture it again.',
        bad_image_dimensions: 'Use a camera image between 64 and 1280 pixels per side, up to 1280 × 720 pixels.',
        bad_payload: 'The recording upload was unreadable. Record it again.',
        bad_frames: 'The camera recording was unreadable. Record it again.',
        bad_frame_count: 'Keep the camera active for the full three-second recording, then try again.',
        bad_timestamps: 'The camera timing was invalid. Record the step again.',
        bad_capture_duration: 'The camera recording was too short or too long. Record it again.',
        bad_wav: 'The audio recording was unreadable. Record the Speak step again.',
        bad_wav_format: 'The audio format was unsupported. Record it again using this page.',
        bad_audio_duration: 'The audio recording was too short or too long. Record the full Speak step again.',
        capture_too_large: 'The camera capture was too large. Use a lower camera resolution.',
        upload_too_large: 'The recording exceeded 8 MiB. Use a lower camera resolution and try again.',
        bad_enrollment_images: 'The enrollment images were unreadable. Enroll again.',
        bad_enrollment_count: 'Capture all five enrollment images using the Enroll button again.',
        too_few_enrollment_samples: 'Not enough enrollment images were usable. Add light, hold still, and enroll again.',
        inconsistent_enrollment: 'The enrollment images did not show a consistent face. Keep only yourself in view and enroll again.',
        invalid_face_embedding: 'The face could not be measured reliably. Hold still and enroll again.',
        bad_audio_timing: 'The audio and camera timing was unreadable. Record Speak again.',
        audio_capture_unavailable: 'This browser could not record synchronized audio. Use a current Chrome or Edge browser.',
        audio_capture_incomplete: 'The microphone recording was interrupted. Record Speak again.',
        landmark_model_missing: 'Face measurement models are not available. Ask the demo operator to check the local model setup.',
        landmark_model_invalid: 'The local face measurement model failed validation. Ask the demo operator to check the setup.',
        insufficient_blink_evidence: 'Keep your eyes visible, face the camera, and record Look again.',
        insufficient_lip_evidence: 'Keep your mouth visible and speak clearly for the full recording, then try Speak again.',
        insufficient_flash_evidence: 'Keep your face visible during the screen flash, then record Look again.',
        invalid_flash_evidence: 'Use even lighting and keep your face visible during the flash, then record Look again.',
        speech_model_missing: 'Speech recognition is not set up. Ask the demo operator to check the local speech model.',
        speech_model_invalid: 'The local speech model failed validation. Ask the demo operator to check the setup.',
        speech_runtime_unavailable: 'Speech recognition is unavailable. Ask the demo operator to check the setup, then try again.',
        speech_configuration_invalid: 'The speech settings need attention. Ask the demo operator to check the setup.',
        verification_unavailable: 'The recording could not be processed. Try again after the demo operator checks the setup.',
        word_not_heard: 'No word was recognized. Say only the displayed word clearly, then try Speak again.',
        wrong_word: 'The recognized word did not match. Say only the displayed word, then try Speak again.',
        ambiguous_word: 'More than one word was recognized. Say the displayed word once, without extra words.',
        word_confidence_low: 'The word was unclear. Reduce background noise and say the displayed word clearly.',
        word_confidence_missing: 'The word could not be verified reliably. Say only the displayed word clearly.',
        word_required: 'This session has no verified word. Start a fresh session with Look.',
        speak_in_progress: 'A Speak recording is still being checked. Wait for it to finish, then try again.',
        speak_attempt_superseded: 'This recording was superseded. Try again when the current check finishes.',
        speak_attempts_exhausted: 'All four Speak attempts were used. Start a fresh session with Look.',
        session_expired: 'This attempt expired after ten minutes. Start a fresh session with Look.',
        session_attempt_superseded: 'This attempt was reopened. Start a fresh session with Look.',
      };
      return messages[reason] || '';
    }

    function enrollMessage(reason) {
      if (captureMessage(reason)) return captureMessage(reason);
      if (reason === 'weak_face' || reason === 'no_face') return 'Move closer and hold still.';
      if (reason === 'model_missing') return 'Face models are not available.';
      return 'Could not enroll that frame.';
    }

    function lookMessage(reason) {
      if (captureMessage(reason)) return captureMessage(reason);
      if (reason === 'no_face') return 'Move closer, face the camera, and add light. Then try the look again.';
      if (reason === 'no_blink') return 'Blink once during the look, then try again.';
      if (reason === 'not_enrolled') return 'Enroll your face before the look.';
      if (reason === 'model_missing') return 'Face models are not available.';
      return 'The look could not be saved. Try again.';
    }

    async function saveEnroll() {
      if (busy) return;
      busy = true;
      setButtons();
      showStatus('');
      metrics.hidden = true;
      try {
        let body;
        if (enrollmentSamples === 5) {
          const images = [];
          for (let index = 0; index < enrollmentSamples; index += 1) {
            prompt.textContent = 'Hold still. Capturing face ' + (index + 1) + ' of 5…';
            images.push(capture());
            if (index + 1 < enrollmentSamples) {
              await new Promise((resolve) => setTimeout(resolve, 200));
            }
          }
          body = { images };
        } else {
          body = { image: capture() };
        }
        const { res, data } = await postJson('/api/face/enroll', body);
        if (res.ok && data.enrolled) {
          enrolled = true;
          prompt.textContent = 'Face enrolled. Start the look and blink once.';
          showStatus('');
        } else {
          showStatus(enrollMessage(data.reason));
        }
      } catch (err) {
        showStatus('Could not reach AuthX.');
      } finally {
        busy = false;
        setButtons();
      }
    }

    function showMetrics(data) {
      if (window.AuthXEvidence) window.AuthXEvidence.show('verification-evidence', data);
      document.getElementById('m-face').textContent = data.faceScore;
      document.getElementById('m-cosine').textContent = data.cosine;
      document.getElementById('m-blink').textContent = data.blinkCount;
      document.getElementById('m-dip').textContent = data.dipPercent;
      document.getElementById('m-delta').textContent = data.reflectionDelta == null ? '—' : data.reflectionDelta;
      document.getElementById('m-r').textContent = data.reflectionR == null ? '—' : data.reflectionR;
      metrics.hidden = false;
    }

    function textOrDash(value) {
      return value == null || value === '' ? '—' : value;
    }

    function showSpeakResult(voice, trust, cert) {
      if (window.AuthXEvidence) window.AuthXEvidence.show('verification-evidence', trust || voice);
      document.getElementById('m-rms').textContent = textOrDash(voice.rms);
      document.getElementById('m-mfcc').textContent = textOrDash(voice.mfccVariation);
      document.getElementById('m-acoustic').textContent = textOrDash(voice.acousticScore);
      document.getElementById('m-lip').textContent = textOrDash(voice.lipR);
      document.getElementById('m-voice').textContent = textOrDash(voice.voiceScore);
      document.getElementById('m-base').textContent = trust ? textOrDash(trust.base) : '—';
      document.getElementById('m-adjust').textContent = trust ? textOrDash(trust.flashAdjust) : '—';
      const trustLine = document.getElementById('m-trust');
      const trustBlock = document.getElementById('trust-block');
      trustBlock.classList.remove('label-safe', 'label-suspicious', 'label-deepfake');
      if (trust && trust.riskLabel) {
        trustLine.textContent = trust.trustScore + ' ' + trust.riskLabel;
        const key = String(trust.riskLabel).toLowerCase();
        if (key === 'safe' || key === 'suspicious' || key === 'deepfake') {
          trustBlock.classList.add('label-' + key);
        }
      } else {
        trustLine.textContent = '—';
      }
      const link = document.getElementById('m-cert');
      if (cert && cert.certId) {
        link.textContent = cert.certId;
        link.href = '/certificate/' + cert.certId;
      } else {
        link.textContent = '—';
        link.removeAttribute('href');
      }
      speakMetrics.hidden = false;
    }

    function concatFloats(chunks) {
      const length = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
      const merged = new Float32Array(length);
      let offset = 0;
      chunks.forEach((chunk) => {
        merged.set(chunk, offset);
        offset += chunk.length;
      });
      return merged;
    }

    function resample(input, fromRate, toRate) {
      if (fromRate === toRate) return input;
      const length = Math.max(1, Math.round(input.length * toRate / fromRate));
      const output = new Float32Array(length);
      for (let index = 0; index < length; index += 1) {
        const position = index * fromRate / toRate;
        const left = Math.floor(position);
        const right = Math.min(left + 1, input.length - 1);
        const mix = position - left;
        output[index] = input[left] * (1 - mix) + input[right] * mix;
      }
      return output;
    }

    function encodeWav(samples, rate) {
      const buffer = new ArrayBuffer(44 + samples.length * 2);
      const view = new DataView(buffer);
      function write(offset, text) {
        for (let index = 0; index < text.length; index += 1) {
          view.setUint8(offset + index, text.charCodeAt(index));
        }
      }
      write(0, 'RIFF');
      view.setUint32(4, 36 + samples.length * 2, true);
      write(8, 'WAVE');
      write(12, 'fmt ');
      view.setUint32(16, 16, true);
      view.setUint16(20, 1, true);
      view.setUint16(22, 1, true);
      view.setUint32(24, rate, true);
      view.setUint32(28, rate * 2, true);
      view.setUint16(32, 2, true);
      view.setUint16(34, 16, true);
      write(36, 'data');
      view.setUint32(40, samples.length * 2, true);
      let offset = 44;
      for (let index = 0; index < samples.length; index += 1) {
        const value = Math.max(-1, Math.min(1, samples[index]));
        view.setInt16(offset, value < 0 ? value * 0x8000 : value * 0x7fff, true);
        offset += 2;
      }
      return buffer;
    }

    function bufferToBase64(buffer) {
      const bytes = new Uint8Array(buffer);
      let binary = '';
      for (let index = 0; index < bytes.length; index += 8192) {
        binary += String.fromCharCode.apply(null, bytes.subarray(index, index + 8192));
      }
      return btoa(binary);
    }

    async function recordSpeech() {
      const audioStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const context = new AudioContext();
      await context.resume();
      const source = context.createMediaStreamSource(audioStream);
      const processor = context.createScriptProcessor(4096, 1, 1);
      const mute = context.createGain();
      mute.gain.value = 0;
      const chunks = [];
      processor.onaudioprocess = (event) => {
        chunks.push(new Float32Array(event.inputBuffer.getChannelData(0)));
      };
      source.connect(processor);
      processor.connect(mute);
      mute.connect(context.destination);
      const frames = [];
      const t0 = performance.now();
      await new Promise((resolve) => {
        const timer = setInterval(() => {
          const elapsed = performance.now() - t0;
          if (frames.length < clipMs / frameEvery && elapsed >= frames.length * frameEvery) {
            frames.push({ tMs: Math.round(elapsed), image: capture() });
          }
          if (elapsed >= clipMs) {
            clearInterval(timer);
            resolve();
          }
        }, 40);
      });
      processor.disconnect();
      source.disconnect();
      audioStream.getTracks().forEach((track) => track.stop());
      const recorded = concatFloats(chunks);
      const merged = recorded.length
        ? resample(recorded, context.sampleRate, sampleRate)
        : new Float32Array(sampleRate);
      await context.close();
      return { wav: bufferToBase64(encodeWav(merged, sampleRate)), frames };
    }

    async function runSpeak() {
      if (busy || !sessionId) return;
      busy = true;
      setButtons();
      showStatus('');
      speakMetrics.hidden = true;
      prompt.textContent = 'Say ' + challengeWord;
      try {
        const clip = captureFrameMs === 50
          ? await window.AuthXCapture.speech(capture, encodeWav, resample, bufferToBase64)
          : await recordSpeech();
        prompt.textContent = 'Checking the voice…';
        const spoken = await postJson('/api/session/' + sessionId + '/speak', clip);
        if (window.AuthXEvidence) window.AuthXEvidence.show('verification-evidence', spoken.data);
        if (!spoken.res.ok && spoken.data.reason !== 'speak_locked') {
          if (spoken.data.freshSessionRequired || spoken.data.reason === 'speak_attempts_exhausted') {
            sessionId = null;
            challengeWord = '';
            wordLine.hidden = true;
            metrics.hidden = true;
            prompt.textContent = 'Start a fresh session with Look.';
            showStatus(captureMessage(spoken.data.reason) || 'Start a fresh session with Look.');
            return;
          }
          prompt.textContent = 'Say ' + challengeWord + ', then try again.';
          const remaining = Number.isInteger(spoken.data.attemptsRemaining)
            ? ' ' + spoken.data.attemptsRemaining + ' Speak attempt(s) remaining.' : '';
          showStatus((captureMessage(spoken.data.reason)
            || (spoken.data.reason === 'no_face' || spoken.data.reason === 'weak_face'
              ? 'Face the camera, move closer, and keep your face visible. Try Speak again.'
              : spoken.data.reason === 'model_missing'
                ? 'Face models are not available.'
                : 'The voice could not be scored. Try the speak step again.')) + remaining);
          return;
        }
        const trust = await postJson('/api/session/' + sessionId + '/trust');
        if (!trust.res.ok && (trust.data.reason === 'word_required' || trust.data.freshSessionRequired
          || trust.data.reason === 'session_attempt_superseded')) {
          sessionId = null;
          challengeWord = '';
          wordLine.hidden = true;
          metrics.hidden = true;
          prompt.textContent = 'Start a fresh session with Look.';
          showStatus(captureMessage(trust.data.reason) || 'Start a fresh session with Look.');
          return;
        }
        const cert = await postJson('/api/session/' + sessionId + '/certificate');
        showSpeakResult(spoken.data, trust.res.ok ? trust.data : null, cert.res.ok ? cert.data : null);
        if (!trust.res.ok || !cert.res.ok) {
          prompt.textContent = 'Say ' + challengeWord + ', then try again.';
          showStatus(trust.res.ok
            ? 'The trust score was saved, but the certificate was not issued. Try again.'
            : 'The voice was saved, but the trust score is not ready. Try again.');
          return;
        }
        prompt.textContent = 'Speak step saved.';
        showStatus('');
        sessionId = null;
      } catch (err) {
        prompt.textContent = 'Say the word, then try the speak step again.';
        showStatus(captureMessage(err && err.captureReason) || (err && err.name === 'NotAllowedError'
          ? 'The microphone could not be opened.'
          : 'Could not reach AuthX.'));
      } finally {
        busy = false;
        setButtons();
      }
    }

    async function runLook() {
      if (busy || !enrolled) return;
      busy = true;
      setButtons();
      showStatus('');
      metrics.hidden = true;
      speakMetrics.hidden = true;
      sessionId = null;
      challengeWord = '';
      wordLine.hidden = true;
      prompt.textContent = 'Blink once now, before the flash';
      if (window.AuthXEvidence) window.AuthXEvidence.show('verification-evidence', null);
      try {
        const started = await postJson('/api/session/start');
        if (!started.res.ok) {
          prompt.textContent = 'Allow the camera, then enroll your face.';
          showStatus(lookMessage(started.data.reason));
          if (started.data.reason === 'not_enrolled') enrolled = false;
          return;
        }
        const flashAt = started.data.flashStartMs;
        captureFrameMs = started.data.captureFrameMs === 50 ? 50 : null;
        let frames = [];
        const t0 = performance.now();
        if (captureFrameMs === 50) {
          frames = await window.AuthXCapture.video(capture, t0, captureFrameMs, (elapsed) => {
            if (elapsed >= flashAt && elapsed < flashAt + flashMs) preview.classList.add('flash');
            else preview.classList.remove('flash');
          });
          preview.classList.remove('flash');
        } else await new Promise((resolve) => {
          const timer = setInterval(() => {
            const elapsed = performance.now() - t0;
            if (elapsed >= flashAt && elapsed < flashAt + flashMs) preview.classList.add('flash');
            else preview.classList.remove('flash');
            if (frames.length < clipMs / 100 && elapsed >= frames.length * 100) {
              frames.push({ tMs: Math.round(elapsed), image: capture() });
            }
            if (elapsed >= clipMs) {
              clearInterval(timer);
              preview.classList.remove('flash');
              resolve();
            }
          }, 40);
        });
        prompt.textContent = 'Checking the look…';
        const uploaded = await postJson('/api/session/' + started.data.sessionId + '/look', { frames });
        if (!uploaded.res.ok) {
          prompt.textContent = 'Blink once, then try the look again.';
          showStatus(lookMessage(uploaded.data.reason));
          return;
        }
        prompt.textContent = 'Look saved. Say the word on the speak step.';
        showStatus('');
        showMetrics(uploaded.data);
        sessionId = started.data.sessionId;
        challengeWord = started.data.word;
        wordLine.hidden = false;
        wordLine.textContent = 'Say: ' + challengeWord;
      } catch (err) {
        prompt.textContent = 'Blink once, then try the look again.';
        showStatus('Could not reach AuthX.');
      } finally {
        busy = false;
        preview.classList.remove('flash');
        setButtons();
      }
    }

    allow.addEventListener('click', async () => {
      showStatus('');
      try {
        await openCamera(camera.value || null);
        await fillCameras();
        allow.hidden = true;
        prompt.textContent = enrolled
          ? 'Face enrolled. Start the look and blink once.'
          : 'Hold still and enroll your face.';
        setButtons();
      } catch (err) {
        showStatus('The camera could not be opened.');
      }
    });
    camera.addEventListener('change', async () => {
      if (!camera.value || busy) return;
      try {
        await openCamera(camera.value);
      } catch (err) {
        showStatus('That camera could not be opened.');
      }
    });
    enroll.addEventListener('click', saveEnroll);
    enrollAgain.addEventListener('click', saveEnroll);
    look.addEventListener('click', runLook);
    speak.addEventListener('click', runSpeak);
    root.hidden = false;
  },
};
