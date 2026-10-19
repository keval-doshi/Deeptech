/* Private bidding dashboard: position board, bid review + checkout,
 * payment result polling and bid history.
 *
 * Every amount here is computed and re-validated by the server. The
 * client-side checks only give fast feedback.
 */
(function () {
  'use strict';
  const { api, escape, icon, inr, date, toast, confirm, setLoading } = window.DTI;

  const STATUS_LABEL = {
    active: 'Active', outbid: 'Outbid', pending_payment: 'Awaiting payment', superseded: 'Superseded',
    expired: 'Expired', cancelled: 'Cancelled', failed: 'Failed',
  };
  const statusPill = (s) => `<span class="status status-${escape(s)}">${escape(STATUS_LABEL[s] || s)}</span>`;
  const crownClass = (p) => (p <= 3 ? `c${p}` : '');

  /* ===================================================================
   * Manage Bids board
   * =================================================================== */
  const board = document.querySelector('[data-bid-board]');
  if (board) {
    const rowsEl = board.querySelector('[data-board-rows]');
    let rules = null;
    let pending = null;
    const set = (sel, html) => { const el = board.querySelector(sel); if (el) el.innerHTML = html; };
    const rankBadge = (p) => `<span class="pr-rank ${crownClass(p)}">${icon('crown', 'pr-crown')}<b>#${p}</b></span>`;

    const renderRows = (data) => {
      const { positions } = data.board;
      if (!positions.length) {
        rowsEl.innerHTML = `<div class="state">${icon('gavel')}<h3>No positions yet</h3><p>Be the first to bid.</p></div>`;
        return;
      }
      rowsEl.innerHTML = positions.map((p) => {
        const qualifying = p.is_open
          ? '<span class="pr-open">Open</span>'
          : `<span class="pr-amount">${inr(p.qualifying_bid)}</span>`;
        const diff = p.qualifying_bid ? `+${inr(p.minimum_next_bid - p.qualifying_bid)} on current` : 'opening bid';
        if (p.is_mine) {
          return `<div class="pr is-mine" role="listitem">
            ${rankBadge(p.position)}
            <div class="pr-cell"><span class="pr-label">Your confirmed bid</span>${qualifying}</div>
            <div class="pr-cell pr-hide-sm"><span class="pr-label">Status</span><span class="pr-you">${icon('check', 'icon-sm')} You hold this spot</span></div>
            <div class="pr-action"><span class="pr-tag">You</span></div>
          </div>`;
        }
        if (!p.higher) {
          return `<div class="pr is-below" role="listitem">
            ${rankBadge(p.position)}
            <div class="pr-cell"><span class="pr-label">Qualifying bid</span>${qualifying}</div>
            <div class="pr-cell pr-hide-sm"><span class="pr-label">Minimum next bid</span><span class="pr-muted">—</span></div>
            <div class="pr-action"><span class="pr-note">Below your spot</span></div>
          </div>`;
        }
        if (!p.eligible) {
          return `<div class="pr is-locked" role="listitem">
            ${rankBadge(p.position)}
            <div class="pr-cell"><span class="pr-label">Qualifying bid</span>${qualifying}</div>
            <div class="pr-cell"><span class="pr-label">Minimum next bid</span><span class="pr-amount">${inr(p.minimum_next_bid)}</span><small>${diff}</small></div>
            <div class="pr-action"><button class="btn btn-ghost btn-sm" type="button" disabled title="${escape(data.board.blocked_message || '')}">${icon('lock', 'icon-sm')} Locked</button></div>
          </div>`;
        }
        return `<div class="pr" role="listitem" data-position="${p.position}" data-min="${p.minimum_next_bid}">
          ${rankBadge(p.position)}
          <div class="pr-cell"><span class="pr-label">Qualifying bid</span>${qualifying}</div>
          <div class="pr-cell"><span class="pr-label">Minimum next bid</span><span class="pr-amount accent">${inr(p.minimum_next_bid)}</span><small>${diff}</small></div>
          <div class="pr-action">
            <div class="pr-bid">
              <div class="input-prefix bid-input"><span>₹</span>
                <input type="number" inputmode="numeric" min="${p.minimum_next_bid}" max="${rules.max_bid}" step="1" value="${p.minimum_next_bid}"
                       aria-label="Your bid for position ${p.position}"></div>
              <button class="btn btn-primary" type="button" data-place-bid>Bid for #${p.position} ${icon('arrow-right', 'icon-sm')}</button>
            </div>
            <span class="bid-error" aria-live="polite"></span>
          </div>
        </div>`;
      }).join('');
    };

    const renderSummary = (data) => {
      const s = data.summary;
      const b = data.board;
      set('[data-current-position]', s.current_position
        ? `<span class="hs-crown ${crownClass(s.current_position)}">${icon('crown')}</span>#${s.current_position}` : '<span class="hs-dim">Unranked</span>');
      set('[data-current-bid]', s.current_bid ? inr(s.current_bid) : '<span class="hs-dim">—</span>');
      let days = '<span class="hs-dim">—</span>';
      if (b.ranking_expires_at && s.current_position) {
        const left = Math.max(0, Math.ceil((new Date(b.ranking_expires_at + 'Z') - Date.now()) / 86400000));
        days = `${left}<small> day${left === 1 ? '' : 's'}</small>`;
      }
      set('[data-days-left]', days);
      const up = s.views_change_pct >= 0;
      set('[data-views]', `${s.views.toLocaleString('en-IN')}<small class="${up ? 'up' : 'down'}">${up ? '▲' : '▼'} ${Math.abs(s.views_change_pct)}%</small>`);
      set('[data-updated]', `Updated ${date(b.updated_at)}`);
      const r = b.rules;
      set('[data-rules-text]', `Opening bid <b>${inr(r.opening_bid)}</b> · steps of <b>${inr(r.increment)}</b> · rankings last <b>${r.ranking_period_days} days</b>`);
    };

    const renderLadder = (data) => {
      const filled = data.board.positions.filter((p) => p.qualifying_bid);
      const el = board.querySelector('[data-ladder]');
      if (!filled.length) { el.innerHTML = '<p class="text-muted mb-0">No confirmed bids yet. Open positions start at the opening bid.</p>'; return; }
      const max = Math.max(...filled.map((p) => p.qualifying_bid));
      el.innerHTML = filled.map((p) => `
        <div class="ladder-row ${p.is_mine ? 'is-mine' : ''}">
          <span class="ladder-pos">#${p.position}</span>
          <span class="ladder-track"><span class="ladder-fill" style="width:${Math.max((p.qualifying_bid / max) * 100, 4)}%"></span></span>
          <span class="ladder-val">${inr(p.qualifying_bid)}${p.is_mine ? ' <em>You</em>' : ''}</span>
        </div>`).join('');
    };

    const renderRecent = (data) => {
      const el = board.querySelector('[data-recent]');
      if (!data.recent.length) { el.innerHTML = '<p class="text-muted mb-0">No bids yet.</p>'; return; }
      el.innerHTML = data.recent.map((b) => `
        <li class="tl-item tl-${escape(b.display_status)}">
          <span class="tl-dot"></span>
          <div class="tl-body">
            <div class="tl-top"><strong>${inr(b.amount)} for #${b.target_position}</strong>${statusPill(b.display_status)}</div>
            <span class="tl-time">${date(b.created_at)}</span>
          </div>
        </li>`).join('');
    };

    const renderLock = (data) => {
      const banner = board.querySelector('[data-lock-banner]');
      const reason = data.board.blocked_reason;
      banner.classList.toggle('hidden', !reason);
      if (!reason) return;
      banner.className = `alert-bar ${reason === 'rejected' ? 'danger' : reason === 'paused' ? 'info' : 'warning'}`;
      let text = data.board.blocked_message;
      if (data.board.rejection_reason) text += ` Reviewer's note: “${data.board.rejection_reason}”`;
      banner.querySelector('[data-lock-text]').textContent = text;
      const actions = { rejected: ['Update company profile', '/dashboard/profile'], pending_review: ['Review your profile', '/dashboard/profile'],
        unverified: ['Account settings', '/dashboard/settings'] };
      const link = banner.querySelector('[data-lock-action]');
      link.hidden = !actions[reason];
      if (actions[reason]) { link.textContent = actions[reason][0]; link.href = actions[reason][1]; }
    };

    const renderPending = (data) => {
      pending = data.board.pending_bid;
      const banner = board.querySelector('[data-pending-banner]');
      banner.classList.toggle('hidden', !pending);
      if (pending) {
        board.querySelector('[data-pending-text]').textContent =
          `You have a ${inr(pending.amount)} bid for #${pending.target_position} awaiting payment (held until ${date(pending.checkout_expires_at)}).`;
      }
    };

    const load = async (manual) => {
      const btn = board.querySelector('[data-refresh]');
      btn.classList.add('is-loading');
      try {
        const data = await api('/api/dashboard/bids');
        rules = data.board.rules;
        renderRows(data);
        renderSummary(data);
        renderLadder(data);
        renderRecent(data);
        renderPending(data);
        renderLock(data);
        if (manual) toast('Positions refreshed.', 'success', 1800);
      } catch (err) {
        rowsEl.innerHTML = `<div class="state error">${icon('alert')}<h3>Couldn't load positions</h3><p>${escape(err.message)}</p></div>`;
      } finally {
        btn.classList.remove('is-loading');
      }
    };

    // Live validation + navigation to review
    const check = (row) => {
      const input = row.querySelector('input');
      const error = row.querySelector('.bid-error');
      const min = +row.dataset.min;
      const raw = input.value.trim();
      let message = '';
      if (!/^\d+$/.test(raw)) message = 'Enter a whole rupee amount.';
      else if (+raw < min) message = `Minimum is ${inr(min)}.`;
      else if (rules && +raw > rules.max_bid) message = `Maximum is ${inr(rules.max_bid)}.`;
      error.textContent = message;
      row.querySelector('.bid-input').classList.toggle('invalid', !!message);
      return message ? null : +raw;
    };
    rowsEl.addEventListener('input', (e) => { const row = e.target.closest('[data-position]'); if (row) check(row); });
    rowsEl.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-place-bid]');
      if (!btn) return;
      const row = btn.closest('[data-position]');
      const amount = check(row);
      if (amount === null) { row.querySelector('input').focus(); return; }
      const url = new URL(board.dataset.reviewUrl, location.origin);
      url.searchParams.set('position', row.dataset.position);
      url.searchParams.set('amount', amount);
      location.href = url.toString();
    });
    rowsEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && e.target.matches('input')) e.target.closest('[data-position]').querySelector('[data-place-bid]')?.click();
    });

    board.querySelector('[data-refresh]').addEventListener('click', () => load(true));
    board.querySelector('[data-resume-pending]').addEventListener('click', async (e) => {
      if (!pending) return;
      setLoading(e.currentTarget, true, 'Opening…');
      try { await startCheckout(pending.id); }
      catch (err) { toast(err.message, 'error'); load(); }
      finally { setLoading(e.currentTarget, false); }
    });
    board.querySelector('[data-cancel-pending]').addEventListener('click', async () => {
      if (!pending) return;
      if (!(await confirm({ title: 'Cancel this bid?', message: 'Your ranking will not change.', confirmText: 'Cancel bid', danger: true }))) return;
      try { await api(`/api/bids/${pending.id}/cancel`, { method: 'POST' }); toast('Bid cancelled.', 'success'); load(); }
      catch (err) { toast(err.message, 'error'); }
    });

    load();
    setInterval(() => { if (!document.hidden) load(); }, 60000);
  }

  /* ===================================================================
   * Checkout (shared by review page and "complete payment")
   * =================================================================== */
  async function startCheckout(bidId) {
    const { checkout } = await api('/api/payments/checkout', { method: 'POST', body: { bid_id: bidId } });
    if (checkout.provider === 'mock') {
      location.href = checkout.redirect_url;
      return;
    }
    if (checkout.provider === 'razorpay') {
      if (typeof window.Razorpay !== 'function') throw new Error('Payment window failed to load. Check your connection and retry.');
      const rzp = new window.Razorpay({
        key: checkout.key,
        order_id: checkout.order_id,
        amount: checkout.amount,
        currency: checkout.currency,
        name: checkout.name,
        description: checkout.description,
        prefill: checkout.prefill,
        theme: { color: '#5b3df5' },
        // The browser callback only redirects. The server waits for the
        // signed webhook (or queries Razorpay itself) before ranking.
        handler: () => { location.href = checkout.result_url; },
        modal: { ondismiss: () => toast('Payment window closed. Your bid is held until the checkout window expires.', 'info', 6000) },
      });
      rzp.on('payment.failed', () => { location.href = checkout.result_url; });
      rzp.open();
      return;
    }
    throw new Error('Unsupported payment provider.');
  }

  /* ===================================================================
   * Review page
   * =================================================================== */
  const review = document.querySelector('[data-bid-review]');
  if (review) {
    const pay = review.querySelector('[data-pay]');
    const terms = review.querySelector('[data-accept-terms]');
    const errorEl = review.querySelector('[data-review-error]');
    const position = +review.dataset.position;
    const amount = +review.dataset.amount;

    // One idempotency key per (position, amount) for this tab, so a double
    // click or a refresh replays the same bid instead of creating another.
    const storeKey = `dti:bid:${position}:${amount}`;
    let key = null;
    try { key = sessionStorage.getItem(storeKey); } catch (_) { /* ignore */ }
    if (!key) {
      key = window.DTI.uuid();
      try { sessionStorage.setItem(storeKey, key); } catch (_) { /* ignore */ }
    }

    terms.addEventListener('change', () => { pay.disabled = !terms.checked; });
    pay.addEventListener('click', async () => {
      if (!terms.checked) return;
      errorEl.textContent = '';
      setLoading(pay, true, 'Securing your bid…');
      try {
        const { bid } = await api('/api/bids', { method: 'POST', body: { position, amount, idempotency_key: key } });
        setLoading(pay, true, 'Opening secure checkout…');
        await startCheckout(bid.id);
        try { sessionStorage.removeItem(storeKey); } catch (_) { /* ignore */ }
      } catch (err) {
        setLoading(pay, false);
        errorEl.textContent = err.message;
        if (err.status === 409 || err.status === 410) {
          try { sessionStorage.removeItem(storeKey); } catch (_) { /* ignore */ }
          errorEl.innerHTML = `${escape(err.message)} <a href="${review.dataset.boardUrl}">Review positions again</a>`;
        }
      }
    });
  }

  /* ===================================================================
   * Result page: poll until the webhook has been processed
   * =================================================================== */
  const result = document.querySelector('[data-bid-result]');
  if (result) {
    const id = result.dataset.bidId;
    let attempts = 0;
    const show = (bid) => {
      const paid = bid.payment_status === 'paid';
      const view = paid ? 'active'
        : bid.status === 'pending_payment' ? 'pending'
        : bid.status === 'failed' ? 'failed' : 'closed';
      result.querySelectorAll('[data-result-view]').forEach((el) => { el.hidden = el.dataset.resultView !== view; });
      result.querySelector('[data-status-text]').textContent = paid ? 'Paid' : (STATUS_LABEL[bid.status] || bid.status);
      if (bid.receipt) result.querySelector('[data-receipt]').textContent = bid.receipt;
      if (paid) {
        const text = result.querySelector('[data-active-text]');
        if (bid.achieved_position === bid.target_position) text.textContent = `You're now ranked #${bid.achieved_position} until ${date(bid.expires_at, false)}.`;
        else if (bid.achieved_position) text.textContent = `Another bid was confirmed first, so you're ranked #${bid.achieved_position}. You can top up from Manage Bids.`;
        else text.textContent = 'Payment received. Our team will contact you about your placement.';
      }
      return view;
    };
    const poll = async () => {
      attempts += 1;
      try {
        const { bid } = await api(`/api/bids/${id}`);
        if (show(bid) === 'pending' && attempts < 40) setTimeout(poll, Math.min(1500 * attempts, 8000));
      } catch (err) {
        if (attempts < 40) setTimeout(poll, 5000);
      }
    };
    poll();
  }

  /* ===================================================================
   * History page
   * =================================================================== */
  const history = document.querySelector('[data-bid-history]');
  if (history) {
    const rows = history.querySelector('[data-history-rows]');
    const pages = history.querySelector('[data-history-pages]');
    const filter = history.querySelector('[data-history-status]');
    let page = 1;
    const load = async () => {
      rows.innerHTML = '<tr><td colspan="8"><div class="skeleton" style="height:28px"></div></td></tr>';
      try {
        const q = new URLSearchParams({ page });
        if (filter.value) q.set('status', filter.value);
        const data = await api(`/api/bids/history?${q}`);
        history.querySelector('[data-paid-total]').textContent = inr(data.paid_total);
        history.querySelector('[data-history-summary]').textContent = `${data.total} bid${data.total === 1 ? '' : 's'}`;
        rows.innerHTML = data.items.length ? data.items.map((b) => `
          <tr>
            <td>${date(b.created_at)}</td>
            <td>#${b.target_position}</td>
            <td>${b.achieved_position ? '#' + b.achieved_position : '—'}</td>
            <td class="num"><strong>${inr(b.amount)}</strong></td>
            <td>${b.payment_status ? `<span class="status status-${escape(b.payment_status)}">${escape(b.payment_status)}</span>` : '—'}</td>
            <td>${b.expires_at ? date(b.expires_at, false) : '—'}</td>
            <td>${statusPill(b.display_status)}</td>
            <td>${b.receipt ? `<a href="/dashboard/bids/result/${b.id}" class="card-link">Details</a>` : ''}</td>
          </tr>`).join('')
          : `<tr><td colspan="8"><div class="state">${icon('history')}<h3>No bids found</h3><p>Bids you place will appear here.</p></div></td></tr>`;
        pages.innerHTML = data.pages > 1 ? Array.from({ length: data.pages }, (_, i) =>
          `<button type="button" data-p="${i + 1}" ${i + 1 === data.page ? 'aria-current="page"' : ''}>${i + 1}</button>`).join('') : '';
      } catch (err) {
        rows.innerHTML = `<tr><td colspan="8"><div class="state error">${icon('alert')}<p>${escape(err.message)}</p></div></td></tr>`;
      }
    };
    filter.addEventListener('change', () => { page = 1; load(); });
    pages.addEventListener('click', (e) => { const b = e.target.closest('[data-p]'); if (b) { page = +b.dataset.p; load(); } });
    load();
  }
})();
