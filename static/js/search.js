/* Startup listings: search, filters, tabs, sorting, pagination / infinite scroll.
 *
 * Markup contract (any element with [data-listing]):
 *   data-endpoint        API URL returning {items, page, pages, total, per_page}
 *   data-per-page        page size
 *   data-view            "rows" (leaderboard) | "grid" (cards)
 *   data-infinite        "true" = append pages as you scroll (with a Load more fallback)
 *   data-sync-url        "true" = mirror filters in the address bar
 *   data-global-filters  "true" = [data-set-filter] controls anywhere on the page filter this list
 *   data-fixed-*         filters that are always sent (e.g. data-fixed-category)
 *   [data-listing-filters]  form whose named controls are filters
 *   [data-filter-control]   extra named controls outside the form
 *   [data-set-filter][data-value]  chips/tabs that set one filter ([data-scroll-to-list] also scrolls)
 *   [data-listing-results|pagination|summary|more|sentinel]  render targets
 */
(function () {
  'use strict';
  const { api, escape, icon } = window.DTI;
  const ICONS = document.body.dataset.icons;
  const AUTO_PAGES = 5; // infinite scroll auto-loads this many pages, then asks

  const verified = (s) => (s.is_verified
    ? `<svg class="icon verified" aria-label="Verified" role="img"><use href="${ICONS}#verified"></use></svg>` : '');

  function logoHtml(s, size = '') {
    return s.logo_url
      ? `<span class="logo-tile ${size}"><img src="${escape(s.logo_url)}" alt="${escape(s.name)} logo" loading="lazy"></span>`
      : `<span class="logo-tile ${size}" style="background:${escape(s.category.color)}" aria-hidden="true">${escape(s.initials)}</span>`;
  }

  function saveButton(s, compact) {
    const label = s.saved ? 'Saved' : 'Save';
    return `<button class="btn btn-ghost ${compact ? 'btn-sm' : ''} save-btn" type="button" data-save-startup="${s.id}"
              aria-pressed="${s.saved}" data-saved-text="Saved" data-unsaved-text="Save" aria-label="Save ${escape(s.name)}">
              ${icon('bookmark', 'icon-sm')}<span data-save-label>${label}</span></button>`;
  }

  function fundingBadge(s) {
    if (s.looking_for_funds) return `<span class="badge badge-primary">${icon('wallet')} Looking for Funds</span>`;
    return s.funding_stage ? `<span class="badge">${escape(s.funding_stage)}</span>` : '';
  }

  /* Leaderboard row (homepage). `n` is the row's place in the list. */
  function rowHtml(s, n) {
    const top = n <= 3 ? `top top-${n}` : '';
    return `
      <article class="lb-row ${top} ${s.promoted_rank ? 'is-promoted' : ''}">
        <span class="lb-rank">#${n}</span>
        ${logoHtml(s)}
        <div class="lb-main">
          <h3><a href="${s.url}" class="lb-link">${escape(s.name)}</a>${verified(s)}
            ${s.promoted_rank ? `<span class="lb-promoted" title="Paid placement">${icon('crown')} Promoted</span>` : ''}</h3>
          <p>${escape(s.tagline)}</p>
          <div class="lb-meta">
            <span>${icon(s.category.icon || 'tag')} ${escape(s.category.name)}</span>
            <span>${icon('map-pin')} ${escape(s.location)}</span>
            ${s.funding_stage ? `<span>${icon('trending-up')} ${escape(s.funding_stage)}</span>` : ''}
            <span class="lb-details">see details</span>
          </div>
        </div>
        <div class="lb-side">
          ${s.looking_for_funds ? `<span class="badge badge-primary">${icon('wallet')} Looking for Funds</span>` : ''}
          ${saveButton(s, true)}
        </div>
      </article>`;
  }

  function cardHtml(s) {
    const rank = s.promoted_rank;
    return `
      <article class="startup-card">
        <a class="thumb" href="${s.url}" tabindex="-1" aria-hidden="true">
          <img src="${escape(s.cover_url)}" alt="" loading="lazy">
          ${rank ? `<span class="rank-badge r${rank}">#${rank}</span>` : ''}
        </a>
        <div class="body">
          ${logoHtml(s, 'sm')}
          <h3><a href="${s.url}">${escape(s.name)}</a>${verified(s)}</h3>
          <div class="row row-wrap" style="gap:8px">
            <span class="badge">${escape(s.category.name)}</span>
            <span class="meta">${icon('map-pin')} ${escape(s.city)}</span>
          </div>
          <p>${escape(s.tagline)}</p>
          ${s.funding ? `<div class="meta">${icon('wallet')} Raising ${escape(s.funding.raising_target || '')} · ${escape(s.funding.stage || '')}</div>` : ''}
          <div class="foot">
            ${fundingBadge(s) || '<span></span>'}
            ${saveButton(s, true)}
          </div>
        </div>
      </article>`;
  }

  function skeleton(view, n) {
    const style = view === 'grid' ? 'style="height:300px;border-radius:16px"' : 'style="height:96px;border-radius:14px"';
    return Array.from({ length: n }, () => `<div class="skeleton" ${style} aria-hidden="true"></div>`).join('');
  }

  function paginationHtml(page, pages) {
    if (pages <= 1) return '';
    const btn = (p, label, attrs = '') => `<button type="button" data-page="${p}" ${attrs}>${label}</button>`;
    const parts = [btn(page - 1, icon('chevron-left', 'icon-sm'), `aria-label="Previous page" ${page <= 1 ? 'disabled' : ''}`)];
    const visible = new Set([1, pages, page - 1, page, page + 1].filter((p) => p >= 1 && p <= pages));
    let prev = 0;
    [...visible].sort((a, b) => a - b).forEach((p) => {
      if (p - prev > 1) parts.push('<span class="gap">…</span>');
      parts.push(btn(p, p, p === page ? 'aria-current="page"' : ''));
      prev = p;
    });
    parts.push(btn(page + 1, icon('chevron-right', 'icon-sm'), `aria-label="Next page" ${page >= pages ? 'disabled' : ''}`));
    return parts.join('');
  }

  function initListing(root) {
    const results = root.querySelector('[data-listing-results]');
    const pager = root.querySelector('[data-listing-pagination]');
    const summary = root.querySelector('[data-listing-summary]');
    const moreBtn = root.querySelector('[data-listing-more]');
    const sentinel = root.querySelector('[data-listing-sentinel]');
    const activityTpl = root.querySelector('[data-activity-template]');
    const form = root.querySelector('[data-listing-filters]');
    const endpoint = root.dataset.endpoint;
    const perPage = root.dataset.perPage || '6';
    const syncUrl = root.dataset.syncUrl === 'true';
    const infinite = root.dataset.infinite === 'true';
    const scope = root.dataset.globalFilters === 'true' ? document : root;
    let view = root.dataset.view || 'rows';
    let controller = null;
    let page = 1;
    let pages = 1;
    let loaded = 0;
    let loading = false;

    const state = {};
    Object.entries(root.dataset).forEach(([key, value]) => {
      if (key.startsWith('fixed')) state[key.slice(5).toLowerCase()] = value;
    });
    const isFixed = (k) => !!root.dataset['fixed' + k[0].toUpperCase() + k.slice(1)];

    // Initial state from URL (shareable searches)
    const params = new URLSearchParams(location.search);
    const controls = () => [
      ...(form ? form.querySelectorAll('[name]') : []),
      ...root.querySelectorAll('[data-filter-control][name]'),
    ];
    controls().forEach((el) => {
      if (!params.has(el.name)) return;
      if (el.type === 'checkbox') el.checked = params.getAll(el.name).includes(el.value) || params.get(el.name) === '1';
      else el.value = params.get(el.name);
    });
    if (!infinite) page = Math.max(parseInt(params.get('page') || '1', 10) || 1, 1);

    function collect() {
      const query = new URLSearchParams();
      const multi = {};
      controls().forEach((el) => {
        if (el.type === 'checkbox') {
          if (el.checked) (multi[el.name] = multi[el.name] || []).push(el.value);
        } else if (el.value) {
          query.set(el.name, el.value);
        }
      });
      Object.entries(multi).forEach(([k, v]) => query.set(k, v.join(',')));
      Object.entries(state).forEach(([k, v]) => { if (v) query.set(k, v); });
      return query;
    }

    function syncChips(query) {
      scope.querySelectorAll('[data-set-filter]').forEach((chip) => {
        if (chip.classList.contains('float-tag') || chip.hasAttribute('data-scroll-to-list')) return;
        const current = query.get(chip.dataset.setFilter) || '';
        const fallback = chip.closest('[role="tablist"]') ? chip.parentElement.querySelector('[data-set-filter]').dataset.value : '';
        const active = (current || fallback) === chip.dataset.value;
        if (chip.getAttribute('role') === 'tab') chip.setAttribute('aria-selected', String(active));
        else { chip.classList.toggle('active', active); chip.setAttribute('aria-pressed', String(active)); }
      });
    }

    function syncAddressBar(query) {
      if (!syncUrl) return;
      const shown = new URLSearchParams(query);
      ['per_page', 'page'].forEach((k) => shown.delete(k));
      if (!infinite && page > 1) shown.set('page', page);
      Object.keys(state).forEach((k) => { if (isFixed(k)) shown.delete(k); });
      if (shown.get('tab') === 'trending') shown.delete('tab');
      if (shown.get('sort') === 'promoted') shown.delete('sort');
      history.replaceState(null, '', `${location.pathname}${shown.toString() ? '?' + shown : ''}${location.hash}`);
    }

    function addMarkers() {
      // "Latest activity" strip after #10 and a "Top 20" divider, like a leaderboard.
      if (view !== 'rows') return;
      const rows = results.querySelectorAll('.lb-row');
      if (activityTpl && rows.length >= 10 && !results.querySelector('.activity-strip')) {
        rows[9].after(activityTpl.content.cloneNode(true));
      }
      if (rows.length > 20 && !results.querySelector('.lb-divider')) {
        rows[19].insertAdjacentHTML('afterend', '<div class="lb-divider"><span>Top 20</span></div>');
      }
    }

    async function load(append = false) {
      const query = collect();
      query.set('page', page);
      query.set('per_page', perPage);
      syncChips(query);
      syncAddressBar(query);
      controller?.abort();
      controller = new AbortController();
      loading = true;
      if (!append) {
        loaded = 0;
        results.className = view === 'grid' ? 'startup-grid' : (infinite ? 'leaderboard' : 'startup-list');
        results.innerHTML = skeleton(view, Math.min(+perPage, 6));
      } else if (moreBtn) {
        window.DTI.setLoading(moreBtn, true, 'Loading…');
      }
      results.setAttribute('aria-busy', 'true');
      try {
        const data = await api(`${endpoint}?${query}`, { signal: controller.signal });
        pages = data.pages;
        const render = view === 'grid' ? cardHtml : (s, i) => rowHtml(s, loaded + i + 1);
        const html = data.items.map((s, i) => render(s, i)).join('');
        if (!append) {
          results.innerHTML = data.items.length ? html
            : `<div class="state">${icon('search')}<h3>No startups match</h3><p>Try a different search term or clear some filters.</p>
               <button class="btn btn-ghost" type="button" data-clear-filters>Clear filters</button></div>`;
        } else {
          results.insertAdjacentHTML('beforeend', html);
        }
        loaded += data.items.length;
        addMarkers();
        if (pager) pager.innerHTML = infinite ? '' : paginationHtml(data.page, data.pages);
        if (summary) {
          if (infinite) {
            summary.textContent = data.total ? `Showing ${loaded.toLocaleString('en-IN')} of ${data.total.toLocaleString('en-IN')} startups` : '';
          } else {
            const start = data.total ? (data.page - 1) * data.per_page + 1 : 0;
            const end = Math.min(data.page * data.per_page, data.total);
            summary.textContent = `Showing ${start}–${end} of ${data.total.toLocaleString('en-IN')} startups`;
          }
        }
        if (moreBtn) {
          window.DTI.setLoading(moreBtn, false);
          moreBtn.hidden = !(infinite && page < pages && page >= AUTO_PAGES);
        }
        root.dispatchEvent(new CustomEvent('listing:loaded', { detail: data }));
      } catch (err) {
        if (err.name === 'AbortError') return;
        if (moreBtn) window.DTI.setLoading(moreBtn, false);
        if (!append) {
          results.innerHTML = `<div class="state error">${icon('alert')}<h3>Couldn't load startups</h3><p>${escape(err.message)}</p>
            <button class="btn btn-ghost" type="button" data-retry>Try again</button></div>`;
          if (pager) pager.innerHTML = '';
          if (summary) summary.textContent = '';
        } else {
          window.DTI.toast(err.message, 'error');
          page -= 1;
        }
      } finally {
        loading = false;
        results.removeAttribute('aria-busy');
      }
    }

    const loadNext = () => {
      if (loading || page >= pages) return;
      page += 1;
      load(true);
    };
    const reload = () => { page = 1; load(); };
    const debounced = window.DTI.debounce(reload, 350);

    form?.addEventListener('submit', (e) => { e.preventDefault(); reload(); });
    controls().forEach((el) => {
      const typing = el.type === 'search' || el.type === 'text';
      el.addEventListener(typing ? 'input' : 'change', typing ? debounced : reload);
    });

    // Filter chips/tabs (anywhere on the page when data-global-filters is set)
    scope.addEventListener('click', (e) => {
      const chip = e.target.closest('[data-set-filter]');
      if (!chip || (scope === root && !root.contains(chip))) return;
      e.preventDefault();
      const name = chip.dataset.setFilter;
      const control = controls().find((el) => el.name === name && el.type !== 'checkbox');
      if (control) control.value = chip.dataset.value;
      else state[name] = chip.dataset.value;
      // A featured-list tab implies its own ordering; reset an explicit sort.
      if (name === 'tab') { const sort = controls().find((el) => el.name === 'sort'); if (sort) sort.value = chip.dataset.value === 'trending' ? 'promoted' : ''; }
      reload();
      if (chip.hasAttribute('data-scroll-to-list')) root.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });

    root.addEventListener('click', (e) => {
      const pageBtn = e.target.closest('[data-page]');
      if (pageBtn && !pageBtn.disabled) {
        page = parseInt(pageBtn.dataset.page, 10);
        load();
        root.scrollIntoView({ behavior: 'smooth', block: 'start' });
        return;
      }
      if (e.target.closest('[data-listing-more]')) { loadNext(); return; }
      if (e.target.closest('[data-retry]')) { load(); return; }
      if (e.target.closest('[data-clear-filters]')) {
        controls().forEach((el) => { if (el.type === 'checkbox') el.checked = false; else if (el.name !== 'sort' && el.name !== 'tab') el.value = ''; });
        Object.keys(state).forEach((k) => { if (!isFixed(k)) delete state[k]; });
        reload();
        return;
      }
      const toggle = e.target.closest('[data-view-toggle]');
      if (toggle) {
        view = toggle.dataset.viewToggle;
        root.querySelectorAll('[data-view-toggle]').forEach((b) => b.setAttribute('aria-pressed', String(b === toggle)));
        try { localStorage.setItem('dti:view', view); } catch (_) { /* private mode */ }
        load();
      }
    });

    if (infinite && sentinel && 'IntersectionObserver' in window) {
      new IntersectionObserver((entries) => {
        if (entries.some((en) => en.isIntersecting) && page < AUTO_PAGES) loadNext();
      }, { rootMargin: '600px 0px' }).observe(sentinel);
    }

    if (root.querySelector('[data-view-toggle]')) {
      try { view = localStorage.getItem('dti:view') || view; } catch (_) { /* ignore */ }
      root.querySelectorAll('[data-view-toggle]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.viewToggle === view)));
    }
    if (location.hash === '#search') {
      // Focus after load: the browser's own jump to #search would otherwise drop it.
      const focusSearch = () => setTimeout(() => root.querySelector('input[type="search"]')?.focus(), 60);
      if (document.readyState === 'complete') focusSearch();
      else window.addEventListener('load', focusSearch, { once: true });
    }
    load();
  }

  document.querySelectorAll('[data-listing]').forEach(initListing);

  // Header search icon on the homepage: focus the search box instead of reloading.
  document.querySelectorAll('[data-search-link]').forEach((link) => link.addEventListener('click', (e) => {
    const input = document.querySelector('#search input[type="search"]');
    if (!input) return;
    e.preventDefault();
    document.getElementById('main-nav')?.classList.remove('open');
    input.closest('#search').scrollIntoView({ behavior: 'smooth', block: 'center' });
    input.focus({ preventScroll: true });
  }));

  window.DTI.renderStartupCard = cardHtml;
  window.DTI.renderStartupRow = rowHtml;
})();
