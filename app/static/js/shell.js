window.AuthXShell = {
  homes: { student: '/student', faculty: '/faculty', admin: '/admin' },
  async requireRole(role) {
    const token = localStorage.getItem('authx_token');
    const who = document.getElementById('who');
    const signOut = document.getElementById('sign-out');
    if (signOut) {
      signOut.addEventListener('click', () => {
        localStorage.removeItem('authx_token');
        localStorage.removeItem('authx_role');
        window.location.href = '/login';
      });
    }
    if (!token) {
      window.location.href = '/login';
      return;
    }
    let res;
    try {
      res = await fetch('/api/auth/me', {
        headers: { Authorization: 'Bearer ' + token },
      });
    } catch (err) {
      window.location.href = '/login';
      return;
    }
    if (!res.ok) {
      localStorage.removeItem('authx_token');
      localStorage.removeItem('authx_role');
      window.location.href = '/login';
      return;
    }
    const me = await res.json();
    const allowed = Array.isArray(role) ? role : [role];
    if (!allowed.includes(me.role)) {
      window.location.href = this.homes[me.role] || '/login';
      return;
    }
    if (who) who.textContent = 'Signed in as ' + me.username + '.';
    return me;
  },
};
