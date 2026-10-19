/* Startup dashboard overview: respond to introduction requests. */
(function () {
  'use strict';
  const { api, toast, confirm, escape } = window.DTI;

  document.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-intro-respond]');
    if (!btn) return;
    const row = btn.closest('[data-intro]');
    const status = btn.dataset.introRespond;
    if (status === 'accepted') {
      const ok = await confirm({ title: 'Accept introduction?', confirmText: 'Accept & share contact',
        message: "The investor will see your startup's contact email, and you'll see theirs." });
      if (!ok) return;
    }
    row.querySelectorAll('button').forEach((b) => { b.disabled = true; });
    try {
      const { introduction } = await api(`/api/introduction-requests/${row.dataset.intro}`, { method: 'PUT', body: { status } });
      const actions = btn.parentElement;
      actions.innerHTML = introduction.investor.email
        ? `<span class="meta">Contact: <a href="mailto:${escape(introduction.investor.email)}">${escape(introduction.investor.email)}</a></span>`
        : '<span class="meta">Declined</span>';
      row.querySelector('.status').className = `status status-${status}`;
      row.querySelector('.status').textContent = status;
      toast(status === 'accepted' ? 'Introduction accepted.' : 'Request declined.', 'success');
    } catch (err) {
      row.querySelectorAll('button').forEach((b) => { b.disabled = false; });
      toast(err.message, 'error');
    }
  });
})();
