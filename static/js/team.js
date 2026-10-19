/* Team page: invite by email, change roles, leave the team. */
(function () {
  'use strict';
  const { api, toast, confirm, setLoading, showFieldErrors, validateForm, escape } = window.DTI;

  const form = document.querySelector('[data-invite-form]');
  form?.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (Object.keys(validateForm(form)).length) return;
    const btn = form.querySelector('[type="submit"]');
    const error = form.querySelector('[data-invite-error]');
    const dev = form.querySelector('[data-invite-dev]');
    error.textContent = '';
    setLoading(btn, true, 'Sending…');
    try {
      const data = await api('/api/team/invites', { method: 'POST', body: { email: form.email.value.trim(), role: form.role.value } });
      toast(`Invitation sent to ${data.invite.email}.`, 'success');
      if (data.dev_link) {
        dev.classList.remove('hidden');
        dev.innerHTML = `Development mode: email not sent. Share this link: <a href="${escape(data.dev_link)}">${escape(data.dev_link)}</a>`;
      } else {
        setTimeout(() => location.reload(), 700);
      }
      form.reset();
    } catch (err) {
      if (err.data?.errors) showFieldErrors(form, err.data.errors);
      error.textContent = err.message;
    } finally {
      setLoading(btn, false);
    }
  });

  document.querySelectorAll('[data-role-select]').forEach((select) => {
    select.addEventListener('change', async () => {
      const role = select.value;
      const ok = await confirm({ title: `Change role to ${role}?`, confirmText: 'Change role',
        message: role === 'owner' ? 'Owners can place bids, see payments and manage the team.' : 'Editors can edit the profile but not bid, pay or manage the team.' });
      if (!ok) { select.value = select.dataset.current; return; }
      try {
        await api(`/api/team/members/${select.dataset.roleSelect}`, { method: 'PUT', body: { role } });
        select.dataset.current = role;
        toast('Role updated.', 'success');
      } catch (err) {
        select.value = select.dataset.current;
        toast(err.message, 'error', 6000);
      }
    });
  });

  document.querySelector('[data-leave]')?.addEventListener('click', async (e) => {
    const ok = await confirm({ title: 'Leave this startup?', confirmText: 'Leave team', danger: true,
      message: "You'll lose access to the dashboard. An owner can invite you again later." });
    if (!ok) return;
    try {
      const data = await api(e.currentTarget.dataset.leave, { method: 'DELETE' });
      location.href = data.redirect || '/';
    } catch (err) {
      toast(err.message, 'error', 6000);
    }
  });
})();
