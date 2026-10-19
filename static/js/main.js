/* DeeptechIndia.in: shared front-end helpers (vanilla JS, no framework).
 * Exposes window.DTI with: api, icon, escape, inr, date, toast, confirm,
 * openModal/closeModal, setLoading, showFieldErrors, debounce, uuid.
 * Security note: nothing here is trusted by the server. Every check is
 * repeated server-side; this file only improves the experience.
 */
(function () {
  'use strict';

  const DTI = (window.DTI = {});
  const body = document.body;
  const ICONS = body.dataset.icons || '/static/images/icons.svg';

  DTI.escape = (value) =>
    String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  DTI.icon = (name, cls = '') => `<svg class="icon ${cls}" aria-hidden="true" focusable="false"><use href="${ICONS}#${name}"></use></svg>`;
  DTI.inr = (n) => (n === null || n === undefined || n === '' ? '—' : '₹' + Number(n).toLocaleString('en-IN'));
  DTI.date = (iso, withTime = true) => {
    if (!iso) return '—';
    const d = new Date(/Z|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + 'Z'); // server sends naive UTC
    const opts = { day: '2-digit', month: 'short', year: 'numeric' };
    if (withTime) Object.assign(opts, { hour: '2-digit', minute: '2-digit', hour12: false });
    return d.toLocaleString('en-IN', opts);
  };
  DTI.debounce = (fn, wait = 300) => {
    let t;
    return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), wait); };
  };
  DTI.uuid = () => {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID().replace(/-/g, '');
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  };
  const csrfToken = () => document.querySelector('meta[name="csrf-token"]')?.content || '';

  /** fetch() wrapper: JSON in/out, CSRF header, consistent errors. */
  DTI.api = async function (url, { method = 'GET', body: data, form, signal } = {}) {
    const headers = { Accept: 'application/json', 'X-Requested-With': 'fetch' };
    let payload;
    if (form) payload = form;
    else if (data !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(data); }
    if (method !== 'GET') headers['X-CSRFToken'] = csrfToken();
    const res = await fetch(url, { method, headers, body: payload, credentials: 'same-origin', signal });
    let json = null;
    try { json = await res.json(); } catch (_) { /* non-JSON */ }
    if (res.status === 401) {
      const next = encodeURIComponent(location.pathname + location.search);
      location.href = `${body.dataset.loginUrl || '/login'}?next=${next}`;
      throw Object.assign(new Error('Sign in required.'), { status: 401, data: json || {} });
    }
    if (!res.ok || (json && json.ok === false)) {
      const message = (json && json.error) || (res.status === 429 ? 'Too many requests. Please wait a moment.' : `Request failed (${res.status}).`);
      throw Object.assign(new Error(message), { status: res.status, data: json || {} });
    }
    return json || {};
  };

  /* ---- Toasts -------------------------------------------------------- */
  DTI.toast = function (message, type = 'info', timeout = 4500) {
    const stack = document.querySelector('[data-toasts]');
    if (!stack) return;
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.setAttribute('role', type === 'error' ? 'alert' : 'status');
    el.innerHTML = DTI.icon(type === 'success' ? 'check' : type === 'error' ? 'alert' : 'info') + '<span></span>';
    el.querySelector('span').textContent = message;
    stack.appendChild(el);
    setTimeout(() => el.remove(), timeout);
  };

  /* ---- Modals -------------------------------------------------------- */
  let lastFocus = null;
  DTI.openModal = function (modal) {
    if (typeof modal === 'string') modal = document.getElementById(modal);
    if (!modal) return;
    lastFocus = document.activeElement;
    modal.classList.add('open');
    body.style.overflow = 'hidden';
    const focusable = modal.querySelector('input, select, textarea, button:not([data-close-modal]), [href]');
    (focusable || modal.querySelector('button'))?.focus();
  };
  DTI.closeModal = function (modal) {
    if (typeof modal === 'string') modal = document.getElementById(modal);
    if (!modal) return;
    modal.classList.remove('open');
    if (!document.querySelector('.modal-backdrop.open')) body.style.overflow = '';
    lastFocus?.focus?.();
  };
  document.addEventListener('click', (e) => {
    const opener = e.target.closest('[data-open-modal]');
    if (opener) { e.preventDefault(); DTI.openModal(opener.dataset.openModal); return; }
    const closer = e.target.closest('[data-close-modal]');
    if (closer) { DTI.closeModal(closer.closest('.modal-backdrop')); return; }
    if (e.target.classList?.contains('modal-backdrop') && !e.target.hasAttribute('data-confirm-modal')) DTI.closeModal(e.target);
  });
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    const open = [...document.querySelectorAll('.modal-backdrop.open')].pop();
    if (open) {
      if (open.hasAttribute('data-confirm-modal')) open.querySelector('[data-confirm-cancel]').click();
      else DTI.closeModal(open);
    }
    closeDropdowns();
  });

  /* ---- Confirmation dialog ------------------------------------------ */
  DTI.confirm = function ({ title = 'Are you sure?', message = '', confirmText = 'Confirm', danger = false } = {}) {
    const modal = document.querySelector('[data-confirm-modal]');
    if (!modal) return Promise.resolve(window.confirm(message || title));
    modal.querySelector('[data-confirm-title]').textContent = title;
    modal.querySelector('[data-confirm-message]').textContent = message;
    const ok = modal.querySelector('[data-confirm-ok]');
    const cancel = modal.querySelector('[data-confirm-cancel]');
    ok.textContent = confirmText;
    ok.className = `btn ${danger ? 'btn-danger' : 'btn-primary'}`;
    DTI.openModal(modal);
    ok.focus();
    return new Promise((resolve) => {
      const done = (value) => {
        ok.removeEventListener('click', yes);
        cancel.removeEventListener('click', no);
        DTI.closeModal(modal);
        resolve(value);
      };
      const yes = () => done(true);
      const no = () => done(false);
      ok.addEventListener('click', yes);
      cancel.addEventListener('click', no);
    });
  };

  // <form data-confirm="message"> or <button data-confirm="message">
  document.addEventListener('submit', async (e) => {
    const form = e.target;
    const trigger = e.submitter && e.submitter.dataset.confirm !== undefined ? e.submitter : form;
    const message = trigger.dataset.confirm;
    if (message === undefined || form.dataset.confirmed === '1') return;
    e.preventDefault();
    const ok = await DTI.confirm({ title: trigger.dataset.confirmTitle || 'Please confirm', message,
      confirmText: trigger.dataset.confirmText || 'Confirm', danger: trigger.dataset.danger !== undefined });
    if (ok) {
      form.dataset.confirmed = '1';
      if (e.submitter && e.submitter.name) {
        const hidden = Object.assign(document.createElement('input'), { type: 'hidden', name: e.submitter.name, value: e.submitter.value });
        form.appendChild(hidden);
      }
      form.submit();
    }
  });

  /* ---- Buttons & forms ----------------------------------------------- */
  DTI.setLoading = function (btn, loading, text) {
    if (!btn) return;
    if (loading) {
      btn.dataset.label = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = `<span class="spinner" aria-hidden="true"></span><span>${DTI.escape(text || 'Please wait…')}</span>`;
    } else {
      btn.disabled = false;
      if (btn.dataset.label) btn.innerHTML = btn.dataset.label;
    }
  };

  DTI.clearFieldErrors = function (form) {
    form.querySelectorAll('.has-error').forEach((f) => f.classList.remove('has-error'));
    form.querySelectorAll('[data-js-error]').forEach((el) => el.remove());
    form.querySelectorAll('[aria-invalid]').forEach((el) => el.removeAttribute('aria-invalid'));
  };
  DTI.showFieldErrors = function (form, errors = {}) {
    DTI.clearFieldErrors(form);
    let first = null;
    Object.entries(errors).forEach(([name, message]) => {
      const input = form.querySelector(`[name="${CSS.escape(name)}"]`);
      const field = input?.closest('.field') || input?.closest('label') || input?.parentElement;
      if (!field) return;
      field.classList.add('has-error');
      input.setAttribute('aria-invalid', 'true');
      const span = document.createElement('span');
      span.className = 'error-text';
      span.dataset.jsError = '';
      span.textContent = message;
      field.appendChild(span);
      first = first || input;
    });
    first?.focus();
  };

  /** Client-side validation mirroring server rules (data-validate forms). */
  DTI.validateForm = function (form) {
    const errors = {};
    form.querySelectorAll('input, select, textarea').forEach((el) => {
      if (!el.name || el.disabled || el.type === 'hidden') return;
      const label = el.closest('.field')?.querySelector('label')?.textContent.replace('*', '').trim() || 'This field';
      const value = el.type === 'checkbox' ? el.checked : el.value.trim();
      if (el.required && !value) errors[el.name] = el.type === 'checkbox' ? 'Please confirm to continue.' : `${label} is required.`;
      else if (value && el.minLength > 0 && el.value.trim().length < el.minLength) errors[el.name] = `${label} must be at least ${el.minLength} characters.`;
      else if (value && el.type === 'email' && !/^[^\s@]+@[^\s@]+\.[a-z]{2,}$/i.test(value)) errors[el.name] = 'Enter a valid email address.';
      else if (value && el.dataset.match && value !== form.querySelector(`[name="${el.dataset.match}"]`)?.value) errors[el.name] = 'Passwords do not match.';
      else if (value && el.type === 'number' && ((el.min !== '' && +value < +el.min) || (el.max !== '' && +value > +el.max))) errors[el.name] = `${label} must be between ${el.min} and ${el.max}.`;
    });
    if (Object.keys(errors).length) DTI.showFieldErrors(form, errors);
    else DTI.clearFieldErrors(form);
    return errors;
  };
  document.addEventListener('submit', (e) => {
    const form = e.target;
    if (!form.matches('form[data-validate]')) return;
    if (Object.keys(DTI.validateForm(form)).length) {
      e.preventDefault();
      e.stopImmediatePropagation();
      return;
    }
    const btn = form.querySelector('[type="submit"]');
    if (btn && !form.dataset.async) DTI.setLoading(btn, true);
  }, true);

  // Live character counters: <textarea data-count="#id">
  document.querySelectorAll('[data-count]').forEach((el) => {
    const out = document.querySelector(el.dataset.count);
    const update = () => { if (out) out.textContent = `${el.value.length} / ${el.maxLength}`; };
    el.addEventListener('input', update);
    update();
  });

  /* ---- Image previews: <input type=file data-preview> inside .dropzone */
  DTI.bindImagePreview = function (input) {
    const zone = input.closest('.dropzone');
    if (!zone) return;
    const show = (file) => {
      zone.querySelector('img.preview')?.remove();
      if (!file) return;
      if (!/^image\/(png|jpe?g|webp)$/.test(file.type)) { DTI.toast('Use a PNG, JPG or WebP image.', 'error'); input.value = ''; return; }
      if (file.size > 5 * 1024 * 1024) { DTI.toast('Images must be smaller than 5 MB.', 'error'); input.value = ''; return; }
      const img = document.createElement('img');
      img.className = 'preview';
      img.alt = 'Selected image preview';
      img.src = URL.createObjectURL(file);
      zone.appendChild(img);
    };
    input.addEventListener('change', () => show(input.files[0]));
    ['dragenter', 'dragover'].forEach((t) => zone.addEventListener(t, () => zone.classList.add('dragover')));
    ['dragleave', 'drop'].forEach((t) => zone.addEventListener(t, () => zone.classList.remove('dragover')));
  };
  document.querySelectorAll('input[type="file"][data-preview]').forEach(DTI.bindImagePreview);

  /* ---- Dropdowns & mobile nav ---------------------------------------- */
  function closeDropdowns(except) {
    document.querySelectorAll('.dropdown-panel.open').forEach((p) => {
      if (p === except) return;
      p.classList.remove('open');
      document.querySelector(`[aria-controls="${p.id}"]`)?.setAttribute('aria-expanded', 'false');
    });
  }
  document.addEventListener('click', (e) => {
    const toggle = e.target.closest('[data-dropdown]');
    if (toggle) {
      const panel = document.getElementById(toggle.getAttribute('aria-controls'));
      const open = !panel.classList.contains('open');
      closeDropdowns(panel);
      panel.classList.toggle('open', open);
      toggle.setAttribute('aria-expanded', String(open));
      if (open && toggle.hasAttribute('data-notifications')) loadNotifications();
      return;
    }
    if (!e.target.closest('.dropdown-panel')) closeDropdowns();
  });
  const navToggle = document.querySelector('[data-nav-toggle]');
  navToggle?.addEventListener('click', () => {
    const nav = document.getElementById('main-nav');
    const open = nav.classList.toggle('open');
    navToggle.setAttribute('aria-expanded', String(open));
  });

  // Homepage: transparent dark header over the hero, solid white after it.
  const hero = document.querySelector('[data-hero]');
  const header = document.querySelector('.site-header');
  if (hero && header) {
    const syncHeader = () => header.classList.toggle('solid', window.scrollY > hero.offsetHeight - header.offsetHeight - 20);
    window.addEventListener('scroll', syncHeader, { passive: true });
    syncHeader();
  }

  // Flash dismiss
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-dismiss]');
    if (btn) btn.closest('.flash')?.remove();
  });

  /* ---- Generic tabs: <div data-tabs> [role=tab][aria-controls] ------- */
  document.querySelectorAll('[data-tabs]').forEach((list) => {
    const tabs = [...list.querySelectorAll('[role="tab"][aria-controls]')];
    const select = (tab, focus) => {
      tabs.forEach((t) => {
        const on = t === tab;
        t.setAttribute('aria-selected', String(on));
        t.tabIndex = on ? 0 : -1;
        const panel = document.getElementById(t.getAttribute('aria-controls'));
        if (panel) panel.hidden = !on;
      });
      if (focus) tab.focus();
      if (list.dataset.tabs === 'hash') history.replaceState(null, '', '#' + tab.getAttribute('aria-controls'));
      tab.dispatchEvent(new CustomEvent('tab:shown', { bubbles: true }));
    };
    tabs.forEach((tab, i) => {
      tab.addEventListener('click', () => select(tab));
      tab.addEventListener('keydown', (e) => {
        const delta = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
        if (delta) select(tabs[(i + delta + tabs.length) % tabs.length], true);
      });
    });
    const fromHash = () => tabs.find((t) => '#' + t.getAttribute('aria-controls') === location.hash);
    select(fromHash() || tabs.find((t) => t.getAttribute('aria-selected') === 'true') || tabs[0]);
    window.addEventListener('hashchange', () => { const tab = fromHash(); if (tab) select(tab); });
  });

  /* ---- Notifications --------------------------------------------------- */
  let notificationsLoaded = false;
  async function loadNotifications() {
    const list = document.querySelector('[data-notif-list]');
    if (!list || notificationsLoaded) return;
    try {
      const data = await DTI.api('/api/notifications');
      notificationsLoaded = true;
      if (!data.items.length) {
        list.innerHTML = '<div class="state" style="border:0;background:none">You are all caught up.</div>';
        return;
      }
      list.innerHTML = data.items.map((n) => `
        <a class="notif-item ${n.read ? '' : 'unread'}" href="${DTI.escape(n.link || '#')}">
          <strong>${DTI.escape(n.title)}</strong>
          ${n.body ? `<span>${DTI.escape(n.body)}</span>` : ''}
          <span>${DTI.date(n.created_at)}</span>
        </a>`).join('');
    } catch (err) {
      list.innerHTML = `<div class="state error" style="border:0">${DTI.escape(err.message)}</div>`;
    }
  }
  document.querySelector('[data-mark-read]')?.addEventListener('click', async () => {
    try {
      await DTI.api('/api/notifications/read', { method: 'POST' });
      document.querySelector('[data-unread]')?.remove();
      document.querySelector('[data-notifications]')?.setAttribute('aria-label', 'Notifications');
      document.querySelectorAll('.notif-item.unread').forEach((n) => n.classList.remove('unread'));
    } catch (err) { DTI.toast(err.message, 'error'); }
  });

  /* ---- Save / follow startup (any page) ------------------------------- */
  document.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-save-startup]');
    if (!btn) return;
    e.preventDefault();
    if (body.dataset.auth !== 'true') {
      location.href = `${body.dataset.loginUrl}?next=${encodeURIComponent(location.pathname)}`;
      return;
    }
    btn.disabled = true;
    try {
      const data = await DTI.api(`/api/startups/${btn.dataset.saveStartup}/save`, { method: 'POST' });
      btn.setAttribute('aria-pressed', String(data.saved));
      const label = btn.querySelector('[data-save-label]');
      if (label) label.textContent = data.saved ? (btn.dataset.savedText || 'Following') : (btn.dataset.unsavedText || 'Follow');
      DTI.toast(data.saved ? 'Saved to your list.' : 'Removed from your list.', 'success', 2500);
    } catch (err) {
      DTI.toast(err.message, 'error');
    } finally {
      btn.disabled = false;
    }
  });
})();
