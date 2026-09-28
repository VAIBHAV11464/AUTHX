window.AuthXEvidence = {
  show(id, data) {
    const target = document.getElementById(id);
    if (!target) return;
    const lines = data && data.evidence && data.evidence.lines;
    target.hidden = !Array.isArray(lines) || !lines.length;
    // Transcripts and labels are text, never HTML.
    target.textContent = Array.isArray(lines) ? lines.join('\n') : '';
    target.style.whiteSpace = 'pre-line';
  },
};
