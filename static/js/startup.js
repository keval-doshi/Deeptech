/* Startup profile page, "List your startup" wizard and the profile editor.
 *
 * Generic API forms: <form data-api-form data-action="/api/..." data-method="POST|PUT"
 *   data-encoding="multipart|json" data-success="Saved." data-then="reload|redirect|reset">
 * Generic delete:    <button data-api-delete="/api/..." data-item-label="founder">
 */
(function () {
  'use strict';
  const { api, escape, toast, confirm, setLoading, showFieldErrors, clearFieldErrors, validateForm } = window.DTI;

  /* ---- Profile tabs (show/hide sections) ------------------------------ */
  const tabList = document.querySelector('[data-profile-tabs]');
  if (tabList) {
    const sections = document.querySelectorAll('[data-profile-sections] [data-section]');
    const show = (key) => {
      tabList.querySelectorAll('[data-show]').forEach((t) => t.setAttribute('aria-selected', String(t.dataset.show === key)));
      sections.forEach((s) => { s.hidden = !s.dataset.section.split(' ').includes(key); });
      history.replaceState(null, '', key === 'overview' ? location.pathname : `#${key}`);
    };
    tabList.addEventListener('click', (e) => {
      const tab = e.target.closest('[data-show]');
      if (tab) show(tab.dataset.show);
    });
    const initial = location.hash.slice(1);
    show(tabList.querySelector(`[data-show="${CSS.escape(initial)}"]`) ? initial : 'overview');
  }

  /* ---- Gallery carousel + lightbox ------------------------------------ */
  const track = document.querySelector('[data-gallery]');
  document.querySelectorAll('[data-gallery-scroll]').forEach((btn) =>
    btn.addEventListener('click', () => track?.scrollBy({ left: +btn.dataset.galleryScroll * track.clientWidth * 0.8, behavior: 'smooth' })));
  const lightbox = document.getElementById('lightbox');
  if (lightbox) {
    const items = [...document.querySelectorAll('[data-lightbox]')];
    let index = 0;
    const render = () => {
      const item = items[index];
      lightbox.querySelector('[data-lightbox-img]').src = item.dataset.lightbox;
      lightbox.querySelector('[data-lightbox-img]').alt = item.dataset.caption || '';
      lightbox.querySelector('[data-lightbox-caption]').textContent = item.dataset.caption || `Image ${index + 1} of ${items.length}`;
    };
    items.forEach((item, i) => item.addEventListener('click', () => { index = i; render(); window.DTI.openModal(lightbox); }));
    lightbox.querySelectorAll('[data-lightbox-step]').forEach((b) => b.addEventListener('click', () => {
      index = (index + +b.dataset.lightboxStep + items.length) % items.length;
      render();
    }));
    document.addEventListener('keydown', (e) => {
      if (!lightbox.classList.contains('open')) return;
      if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
        index = (index + (e.key === 'ArrowRight' ? 1 : -1) + items.length) % items.length;
        render();
      }
    });
  }

  /* ---- Copy profile link ---------------------------------------------- */
  document.querySelector('[data-copy-link]')?.addEventListener('click', async () => {
    const input = document.querySelector('[data-share-url]');
    try { await navigator.clipboard.writeText(input.value); toast('Link copied.', 'success', 2000); }
    catch (_) { input.select(); document.execCommand('copy'); }
  });

  /* ---- Introduction request (investors) --------------------------------- */
  const introForm = document.querySelector('[data-intro-form]');
  introForm?.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (Object.keys(validateForm(introForm)).length) return;
    const btn = introForm.querySelector('[type="submit"]');
    setLoading(btn, true, 'Sending…');
    try {
      await api('/api/introduction-requests', { method: 'POST', body: {
        startup_id: +introForm.dataset.startupId, message: introForm.message.value.trim() } });
      window.DTI.closeModal(introForm.closest('.modal-backdrop'));
      toast('Introduction request sent. We will notify you when the team responds.', 'success');
      document.querySelectorAll('[data-open-modal="intro-modal"]').forEach((b) => { b.disabled = true; b.textContent = 'Introduction pending'; });
    } catch (err) {
      if (err.data?.errors) showFieldErrors(introForm, err.data.errors);
      toast(err.message, 'error');
    } finally {
      setLoading(btn, false);
    }
  });

  /* ---- Generic API forms ------------------------------------------------ */
  function formPayload(form) {
    if (form.dataset.encoding === 'json') {
      const data = {};
      new FormData(form).forEach((value, key) => {
        if (key === 'csrf_token') return;
        if (key.endsWith('[]')) (data[key.slice(0, -2)] = data[key.slice(0, -2)] || []).push(value);
        else data[key] = value;
      });
      form.querySelectorAll('input[type="checkbox"]:not([name$="[]"])').forEach((cb) => { data[cb.name] = cb.checked; });
      return { body: data };
    }
    return { form: new FormData(form) };
  }

  document.querySelectorAll('form[data-api-form]').forEach((form) => {
    form.dataset.async = '1';
    form.noValidate = true;
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (Object.keys(validateForm(form)).length) {
        toast('Please fix the highlighted fields.', 'error');
        return;
      }
      const btn = e.submitter || form.querySelector('[type="submit"]');
      setLoading(btn, true, form.dataset.loadingText || 'Saving…');
      try {
        const result = await api(form.dataset.action, { method: form.dataset.method || 'POST', ...formPayload(form) });
        clearFieldErrors(form);
        toast(form.dataset.success || 'Saved.', 'success');
        const then = form.dataset.then || 'reload';
        if (then === 'redirect' && result.redirect) setTimeout(() => { location.href = result.redirect; }, 600);
        else if (then === 'reload') setTimeout(() => location.reload(), 500);
        else if (then === 'reset') form.reset();
      } catch (err) {
        if (err.data?.errors) showFieldErrors(form, err.data.errors);
        toast(err.message, 'error', 6000);
      } finally {
        setLoading(btn, false);
      }
    });
  });

  document.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-api-delete]');
    if (!btn) return;
    const ok = await confirm({ title: `Remove ${btn.dataset.itemLabel || 'item'}?`,
      message: 'This cannot be undone.', confirmText: 'Remove', danger: true });
    if (!ok) return;
    btn.disabled = true;
    try {
      await api(btn.dataset.apiDelete, { method: 'DELETE' });
      btn.closest('[data-item]')?.remove();
      toast('Removed.', 'success', 2000);
    } catch (err) {
      btn.disabled = false;
      toast(err.message, 'error');
    }
  });

  /* ---- List-your-startup: raising toggle + live preview ------------------ */
  const raising = document.querySelector('[name="is_raising"]');
  const raisingFields = document.querySelector('[data-raising-fields]');
  if (raising && raisingFields) {
    const sync = () => {
      raisingFields.hidden = !raising.checked;
      raisingFields.querySelectorAll('select, input').forEach((el) => { el.required = raising.checked && el.dataset.requiredWhenRaising !== undefined; });
    };
    raising.addEventListener('change', sync);
    sync();
  }
  const preview = document.querySelector('[data-live-preview]');
  if (preview) {
    const form = preview.closest('form') || document;
    const name = form.querySelector('[name="name"]');
    const tagline = form.querySelector('[name="tagline"]');
    const category = form.querySelector('[name="category_id"]');
    const city = form.querySelector('[name="city"]');
    const update = () => {
      preview.querySelector('[data-p-name]').textContent = name.value.trim() || 'Your startup';
      preview.querySelector('[data-p-tagline]').textContent = tagline.value.trim() || 'Your one-line tagline appears here.';
      preview.querySelector('[data-p-category]').textContent = category.selectedOptions[0]?.dataset.label || 'Category';
      preview.querySelector('[data-p-city]').textContent = city.value.trim() || 'City';
      const initials = name.value.trim().split(/\s+/).slice(0, 2).map((w) => w[0] || '').join('').toUpperCase();
      const logo = preview.querySelector('[data-p-logo]');
      if (!logo.querySelector('img')) logo.textContent = initials || 'S';
    };
    [name, tagline, category, city].forEach((el) => el?.addEventListener('input', update));
    category?.addEventListener('change', update);
    form.querySelector('[name="logo"]')?.addEventListener('change', (e) => {
      const file = e.target.files[0];
      const logo = preview.querySelector('[data-p-logo]');
      if (file && /^image\//.test(file.type)) logo.innerHTML = `<img src="${escape(URL.createObjectURL(file))}" alt="">`;
    });
    update();
  }
})();
