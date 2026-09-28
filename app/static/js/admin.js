window.AuthXAdmin = {
  async load() {
    const token = localStorage.getItem('authx_token');
    const status = document.getElementById('admin-status');
    const list = document.getElementById('cert-list');
    let res;
    try {
      res = await fetch('/api/admin/summary', {
        headers: { Authorization: 'Bearer ' + token },
      });
    } catch (err) {
      status.textContent = 'Could not reach AuthX.';
      return;
    }
    if (!res.ok) {
      status.textContent = 'The admin summary could not be loaded.';
      return;
    }
    const data = await res.json();
    const counts = data.counts || {};
    document.getElementById('count-safe').textContent = counts.SAFE || 0;
    document.getElementById('count-suspicious').textContent = counts.SUSPICIOUS || 0;
    document.getElementById('count-deepfake').textContent = counts.DEEPFAKE || 0;
    list.replaceChildren();
    (data.certificates || []).forEach((cert) => {
      const item = document.createElement('li');
      item.className = 'cert-card';
      const key = String(cert.riskLabel || '').toLowerCase();
      if (key === 'safe' || key === 'suspicious' || key === 'deepfake') {
        item.classList.add('label-' + key);
      }
      const text = document.createElement('span');
      text.textContent = cert.certId + ' · ' + cert.username + ' · ' + (cert.riskLabel || 'no label');
      item.appendChild(text);
      if (cert.revoked) {
        const note = document.createElement('span');
        note.className = 'muted';
        note.textContent = ' · revoked';
        item.appendChild(note);
      } else {
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = 'Revoke';
        button.addEventListener('click', () => revoke(cert.certId, button, item));
        item.appendChild(button);
      }
      list.appendChild(item);
    });
    status.textContent = data.certificates && data.certificates.length ? '' : 'No certificates yet.';

    async function revoke(certId, button, item) {
      button.disabled = true;
      let response;
      try {
        response = await fetch('/api/admin/certificates/' + certId + '/revoke', {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + token },
        });
      } catch (err) {
        button.disabled = false;
        status.textContent = 'Could not reach AuthX.';
        return;
      }
      if (!response.ok) {
        button.disabled = false;
        status.textContent = 'That certificate could not be revoked.';
        return;
      }
      button.remove();
      const note = document.createElement('span');
      note.className = 'muted';
      note.textContent = ' · revoked';
      item.appendChild(note);
      status.textContent = certId + ' revoked. The hash was not changed.';
    }
  },
};
