(function () {
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduce) return;

  const root = document.documentElement;
  let targetX = window.innerWidth * 0.28;
  let targetY = window.innerHeight * 0.22;
  let x = targetX;
  let y = targetY;

  window.addEventListener('pointermove', (event) => {
    targetX = event.clientX;
    targetY = event.clientY;
  });

  function frame(time) {
    x += (targetX - x) * 0.06;
    y += (targetY - y) * 0.06;
    const seconds = time / 1000;
    const driftX = Math.sin(seconds * 0.35) * 48;
    const driftY = Math.cos(seconds * 0.28) * 36;
    root.style.setProperty('--wash-x', (x - 240 + driftX) + 'px');
    root.style.setProperty('--wash-y', (y - 220 + driftY) + 'px');
    root.style.setProperty('--wash-x2', (window.innerWidth - x - 180 + Math.cos(seconds * 0.22) * 56) + 'px');
    root.style.setProperty('--wash-y2', (window.innerHeight - y - 160 + Math.sin(seconds * 0.31) * 44) + 'px');
    window.requestAnimationFrame(frame);
  }

  window.requestAnimationFrame(frame);
})();
