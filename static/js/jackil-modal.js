/* Shared modal behaviour (M1 p02). One overlay stack: Esc, scrim click and
   [data-modal-close] close the top modal; [data-modal-open="<id>"] opens one. */
const JackilModal = {
  stack: [],

  FOCUSABLE: 'button:not([disabled]), [href], input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])',

  _all(selector, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(selector));
  },

  _visible(el) {
    return el.offsetParent !== null;
  },

  _focusables(overlay) {
    return this._all(this.FOCUSABLE, overlay).filter((el) => this._visible(el));
  },

  _setInert(on) {
    for (const sel of ['.sidebar', '.main']) {
      const el = document.querySelector(sel);
      if (el) el.inert = on;
    }
  },

  open(id, trigger) {
    const el = document.getElementById(id);
    if (!el || this.stack.some((entry) => entry.el === el)) return;
    this.stack.push({ el, trigger: trigger || document.activeElement });

    el.classList.add('active');
    this._setInert(true);

    requestAnimationFrame(() => {
      const scope = el.querySelector('.modal') || el;
      const field = scope.querySelector('input:not([disabled]), select:not([disabled]), textarea:not([disabled])');
      const target = field || this._focusables(el)[0];
      if (target) target.focus({ preventScroll: true });
    });
  },

  close() {
    const top = this.stack.pop();
    if (!top) return;
    top.el.classList.remove('active');
    if (this.stack.length === 0) this._setInert(false);
    const trigger = top.trigger;
    if (trigger && typeof trigger.focus === 'function' && document.contains(trigger)) {
      trigger.focus({ preventScroll: true });
    }
  },

  handleKeydown(e) {
    if (!this.stack.length) return;
    const top = this.stack[this.stack.length - 1].el;
    if (e.key === 'Escape') {
      e.preventDefault();
      this.close();
      return;
    }
    if (e.key !== 'Tab') return;
    const focusables = this._focusables(top);
    if (!focusables.length) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  },

  handleClick(e) {
    const opener = e.target.closest ? e.target.closest('[data-modal-open]') : null;
    if (opener) {
      e.preventDefault();
      this.open(opener.dataset.modalOpen, opener);
      return;
    }
    if (!this.stack.length) return;
    const top = this.stack[this.stack.length - 1].el;
    const closer = e.target.closest ? e.target.closest('[data-modal-close]') : null;
    if (closer && top.contains(closer)) {
      this.close();
      return;
    }
    if (e.target === top) this.close();
  },
};

document.addEventListener('keydown', (e) => JackilModal.handleKeydown(e));
document.addEventListener('click', (e) => JackilModal.handleClick(e));

window.JackilModal = JackilModal;
