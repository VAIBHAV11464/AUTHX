window.AuthXFaculty = {
  async loadList() {
    const list = document.getElementById('session-list');
    const status = document.getElementById('faculty-status');
    const token = localStorage.getItem('authx_token');
    let res;
    try {
      res = await fetch('/api/faculty/sessions', {
        headers: { Authorization: 'Bearer ' + token },
      });
    } catch (err) {
      status.textContent = 'Could not reach AuthX.';
      return;
    }
    if (!res.ok) {
      status.textContent = 'Sessions could not be loaded.';
      return;
    }
    const data = await res.json();
    list.replaceChildren();
    (data.sessions || []).forEach((session) => {
      const item = document.createElement('li');
      const link = document.createElement('a');
      link.href = '/faculty/session/' + session.sessionId;
      const label = session.riskLabel || session.status;
      link.textContent = session.username + ' · ' + session.word + ' · ' + label;
      item.appendChild(link);
      list.appendChild(item);
    });
    status.textContent = data.sessions && data.sessions.length ? '' : 'No sessions yet.';
  },

  paintLabel(label) {
    const hero = document.getElementById('trust-hero');
    if (!hero) return;
    hero.classList.remove('label-safe', 'label-suspicious', 'label-deepfake');
    const key = String(label || '').toLowerCase();
    if (key === 'safe' || key === 'suspicious' || key === 'deepfake') {
      hero.classList.add('label-' + key);
    }
  },

  bindDetail(sessionId) {
    const status = document.getElementById('faculty-status');
    AuthXShell.requireRole(['faculty', 'admin']).then((me) => {
      if (!me) return;
      load(me);
    });

    async function load() {
      const token = localStorage.getItem('authx_token');
      let res;
      try {
        res = await fetch('/api/faculty/sessions/' + sessionId, {
          headers: { Authorization: 'Bearer ' + token },
        });
      } catch (err) {
        status.hidden = false;
        status.textContent = 'Could not reach AuthX.';
        return;
      }
      if (res.status === 404) {
        document.getElementById('session-title').textContent = 'Session not found';
        return;
      }
      if (!res.ok) {
        status.hidden = false;
        status.textContent = 'This session could not be loaded.';
        return;
      }
      const data = await res.json();
      document.getElementById('session-title').textContent = data.username;
      if (window.AuthXEvidence) window.AuthXEvidence.show('session-evidence', data);
      document.getElementById('session-line').textContent =
        data.word + ' · flash ' + data.flashStartMs + ' ms · ' + (data.riskLabel || 'no label');
      const fields = {
        'm-face': data.faceScore,
        'm-cosine': data.cosine,
        'm-blink': data.blinkCount,
        'm-dip': data.dipPercent,
        'm-flash': data.flashScore,
        'reflection-delta': data.reflectionDelta,
        'reflection-r': data.reflectionR,
        'm-acoustic': data.acousticScore,
        'm-lip': data.lipR,
        'm-voice': data.voiceScore,
        'm-rms': data.rms,
        'm-mfcc': data.mfccVariation,
        'trust-score': data.trustScore,
        'trust-label': data.riskLabel || '—',
      };
      Object.keys(fields).forEach((id) => {
        const value = fields[id];
        document.getElementById(id).textContent = value == null || value === '' ? '—' : value;
      });
      AuthXFaculty.paintLabel(data.riskLabel);
      document.getElementById('session-metrics').hidden = false;
      document.getElementById('faculty-actions').hidden = false;
      document.querySelectorAll('[data-label]').forEach((button) => {
        button.addEventListener('click', () => send(button.dataset.label));
      });
      document.getElementById('send-back').addEventListener('click', sendBack);
    }

    async function send(label) {
      const token = localStorage.getItem('authx_token');
      status.hidden = false;
      let res;
      try {
        res = await fetch('/api/faculty/sessions/' + sessionId + '/override', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: 'Bearer ' + token,
          },
          body: JSON.stringify({ label }),
        });
      } catch (err) {
        status.textContent = 'Could not reach AuthX.';
        return;
      }
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        status.textContent = 'The label could not be changed.';
        return;
      }
      document.getElementById('trust-label').textContent = data.riskLabel;
      AuthXFaculty.paintLabel(data.riskLabel);
      const line = document.getElementById('session-line');
      if (line.textContent) {
        line.textContent = line.textContent.replace(/ · [^·]+$/, ' · ' + data.riskLabel);
      }
      status.textContent = 'Label set to ' + data.riskLabel + '.';
      if (window.AuthXEvidence && data.evidence) window.AuthXEvidence.show('session-evidence', data);
    }

    async function sendBack() {
      const token = localStorage.getItem('authx_token');
      status.hidden = false;
      let res;
      try {
        res = await fetch('/api/session/' + sessionId + '/reopen', {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + token },
        });
      } catch (err) {
        status.textContent = 'Could not reach AuthX.';
        return;
      }
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        status.textContent = data.reason === 'session_expired'
          ? 'This attempt expired. The student must start a fresh session with Look.'
          : data.reason === 'speak_attempts_exhausted'
            ? 'All Speak attempts were used. The student must start a fresh session with Look.'
            : data.reason === 'speak_in_progress'
              ? 'A Speak check is still running. Wait for it to finish.'
              : 'The session could not be sent back.';
        return;
      }
      if (data.newSession && data.sessionId) {
        window.location.assign('/faculty/session/' + encodeURIComponent(data.sessionId));
        return;
      }
      ['m-face', 'm-cosine', 'm-blink', 'm-dip', 'm-flash', 'reflection-delta', 'reflection-r',
        'm-acoustic', 'm-lip', 'm-voice', 'm-rms', 'm-mfcc', 'trust-score'].forEach((id) => {
        document.getElementById(id).textContent = '—';
      });
      document.getElementById('trust-label').textContent = '—';
      AuthXFaculty.paintLabel('');
      if (window.AuthXEvidence) window.AuthXEvidence.show('session-evidence', null);
      status.textContent = 'Sent back. The student can run the look and speak steps again.';
      const line = document.getElementById('session-line');
      if (line.textContent) line.textContent = line.textContent.replace(/ · [^·]+$/, ' · no label');
    }
  },
};
