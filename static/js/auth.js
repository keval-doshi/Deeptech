/* Registration: show investor-only fields when the investor role is chosen. */
(function () {
  'use strict';
  const block = document.querySelector('[data-investor-only]');
  if (!block) return;
  const sync = () => {
    const investor = document.querySelector('input[name="role"]:checked')?.value === 'investor';
    block.hidden = !investor;
    const firm = block.querySelector('input');
    firm.required = investor;
    firm.disabled = !investor;
  };
  document.querySelectorAll('input[name="role"]').forEach((r) => r.addEventListener('change', sync));
  sync();
})();
