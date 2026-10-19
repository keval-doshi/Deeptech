/* Investor directory + investor workspace (saved startups, intros, fund profile). */
(function () {
  'use strict';
  const { api, escape, icon, date, toast, setLoading, showFieldErrors, debounce } = window.DTI;

  /* ---- Directory --------------------------------------------------------- */
  const directory = document.querySelector('[data-investor-directory]');
  if (directory) {
    if (directory.dataset.moveInto) document.getElementById(directory.dataset.moveInto)?.appendChild(directory);
    const form = directory.querySelector('[data-directory-filters]');
    const results = directory.querySelector('[data-directory-results]');
    let controller;
    const load = async () => {
      controller?.abort();
      controller = new AbortController();
      results.innerHTML = Array.from({ length: 3 }, () => '<div class="skeleton" style="height:190px;border-radius:16px"></div>').join('');
      try {
        const data = await api(`/api/investors?${new URLSearchParams(new FormData(form))}`, { signal: controller.signal });
        results.innerHTML = data.items.length ? data.items.map((i) => `
          <article class="card investor-card">
            <div class="top">${i.logo_url ? `<span class="logo-tile sm" style="background:#fff;border:1px solid var(--border)"><img src="${escape(i.logo_url)}" alt=""></span>` : `<span class="logo-tile sm">${escape(i.initials)}</span>`}
              <div><strong style="color:var(--ink);display:flex;gap:6px;align-items:center">${escape(i.firm_name)}${i.is_verified ? icon('verified', 'verified') : ''}</strong>
              <span class="meta">${escape(i.investor_type)}${i.city ? ' · ' + escape(i.city) : ''}</span></div></div>
            <p>${escape(i.thesis)}</p>
            ${i.cheque_size ? `<span class="meta">${icon('wallet')} Cheque ${escape(i.cheque_size)}</span>` : ''}
            ${i.stages.length ? `<span class="meta">${icon('trending-up')} ${i.stages.map(escape).join(', ')}</span>` : ''}
            <div class="tag-list">${i.categories.map((c) => `<span class="badge badge-primary">${escape(c)}</span>`).join('')}</div>
          </article>`).join('')
          : `<div class="state" style="grid-column:1/-1">${icon('users')}<h3>No investors match</h3><p>Try a broader search.</p></div>`;
      } catch (err) {
        if (err.name === 'AbortError') return;
        results.innerHTML = `<div class="state error" style="grid-column:1/-1">${icon('alert')}<p>${escape(err.message)}</p></div>`;
      }
    };
    form.addEventListener('submit', (e) => { e.preventDefault(); load(); });
    form.querySelector('[name="q"]').addEventListener('input', debounce(load, 350));
    form.querySelectorAll('select').forEach((s) => s.addEventListener('change', load));
    load();
  }

  /* ---- Workspace ----------------------------------------------------------- */
  const ws = document.querySelector('[data-investor-workspace]');
  if (!ws) return;
  const card = window.DTI.renderStartupCard;
  const emptyState = (iconName, title, text) => `<div class="state" style="grid-column:1/-1">${icon(iconName)}<h3>${title}</h3><p>${text}</p></div>`;

  async function load() {
    try {
      const data = await api('/api/investors/me');
      ws.querySelector('[data-recommended]').innerHTML = data.recommended.length
        ? data.recommended.map(card).join('') : emptyState('sparkles', 'Pick your sectors', 'Add sectors to your fund profile to get recommendations.');
      ws.querySelector('[data-saved]').innerHTML = data.saved.length
        ? data.saved.map(card).join('') : emptyState('bookmark', 'Nothing saved yet', 'Use the Save button on any startup to track it here.');
      ws.querySelector('[data-count-saved]').textContent = data.saved.length;
      ws.querySelector('[data-count-intros]').textContent = data.introductions.length;
      ws.querySelector('[data-intros]').innerHTML = data.introductions.length ? data.introductions.map((i) => `
        <tr><td><a href="/startups/${escape(i.startup.slug)}">${escape(i.startup.name)}</a></td>
        <td>${date(i.created_at, false)}</td><td style="max-width:380px">${escape(i.message)}</td>
        <td><span class="status status-${escape(i.status)}">${escape(i.status)}</span></td>
        <td>${i.startup.email ? `<a href="mailto:${escape(i.startup.email)}">${escape(i.startup.email)}</a>` : '<span class="text-subtle">After acceptance</span>'}</td></tr>`).join('')
        : `<tr><td colspan="5">${emptyState('send', 'No introductions yet', 'Open a startup profile and choose “Request Introduction”.')}</td></tr>`;

      const form = ws.querySelector('[data-investor-form]');
      const p = data.profile;
      ['firm_name', 'investor_type', 'thesis', 'website', 'city', 'check_min_inr', 'check_max_inr'].forEach((k) => {
        if (form[k]) form[k].value = p[k] ?? '';
      });
      form.firm_name.value = p.firm_name;
      form.investor_type.value = p.investor_type;
      form.stages.value = p.stages.join(', ');
      form.querySelectorAll('[name="category_ids"]').forEach((cb) => {
        cb.checked = p.category_ids.includes(+cb.value);
        cb.closest('.chip').classList.toggle('active', cb.checked);
      });
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  const form = ws.querySelector('[data-investor-form]');
  form.addEventListener('change', (e) => {
    if (e.target.name === 'category_ids') e.target.closest('.chip').classList.toggle('active', e.target.checked);
  });
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (Object.keys(window.DTI.validateForm(form)).length) return;
    const btn = form.querySelector('[type="submit"]');
    setLoading(btn, true, 'Saving…');
    const body = Object.fromEntries(['firm_name', 'investor_type', 'thesis', 'website', 'city', 'check_min_inr', 'check_max_inr', 'stages']
      .map((k) => [k, form[k].value]));
    body.category_ids = [...form.querySelectorAll('[name="category_ids"]:checked')].map((cb) => +cb.value);
    try {
      await api('/api/investors/me', { method: 'PUT', body });
      toast('Fund profile saved.', 'success');
      load();
    } catch (err) {
      if (err.data?.errors) showFieldErrors(form, err.data.errors);
      toast(err.message, 'error');
    } finally {
      setLoading(btn, false);
    }
  });
  load();
})();
