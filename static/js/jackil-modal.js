/* Shared modal behaviour (M1 p02). One overlay stack: Esc, scrim click and
   [data-modal-close] close the top modal; [data-modal-open="<id>"] opens one.
   prompt()/confirm() are promise-returning dialogs on the same stack, so a
   dashboard toolbar button can await an answer instead of taking a callback. */
const JackilModal = {
  stack: [],

  /* Per-dialog state for the two promise dialogs: the words to write into a
     reused overlay when it opens, and what dismissing it means. Declared here
     rather than after the object literal so nothing can reach open()/close()
     before they exist. */
  _text: {},
  _cancellers: {},

  _all(sel, root) {
    return Array.from((root || document).querySelectorAll(sel));
  },

  open(id, trigger) {
    const el = typeof id === 'string' ? document.getElementById(id) : id;
    if (!el) return;
    this._last = { id: el.id, trigger: trigger || document.activeElement };
    this.stack.push(el);
    el.classList.add('active');
    el.setAttribute('aria-hidden', 'false');
    // A reused dialog overlay carries the previous call's words until they are
    // rewritten — which happens here, after the node is visible and before
    // anything reads it.
    const write = this._text[el.id];
    if (write) write(el);
    // Park focus on the first control that can take it — otherwise Esc has no
    // listener to reach inside an overlay the click never focused.
    const field = el.querySelector('input:not([type=hidden]), select, textarea, button');
    if (field) field.focus();
  },

  close() {
    const el = this.stack.pop();
    if (!el) return;
    el.classList.remove('active');
    el.setAttribute('aria-hidden', 'true');
    // Dismissing a dialog by Esc or scrim is an answer — "nothing" — and the
    // caller awaiting it has to hear it. Plain overlays carry no hook.
    const cancel = this._cancellers[el.id];
    if (cancel) cancel();
    const last = this._last;
    if (last && last.id === el.id && last.trigger && last.trigger.focus) last.trigger.focus();
  },

  handleKeydown(e) {
    if (!this.stack.length) return;
    const top = this.stack[this.stack.length - 1];
    if (e.key === 'Escape') {
      e.preventDefault();
      this.close();
      return;
    }
    // Tab is scoped to the open overlay so a modal behaves like one: focus
    // cannot wander into the page behind it and activate an unseen button.
    if (e.key !== 'Tab') return;
    const controls = this._all(
      'a[href], button:not([disabled]), input:not([type=hidden]), select, textarea, [tabindex]:not([tabindex="-1"])',
      top,
    ).filter((el) => !el.hasAttribute('hidden') && el.offsetParent !== null);
    if (!controls.length) return;
    const first = controls[0];
    const last = controls[controls.length - 1];
    if (e.shiftKey && (document.activeElement === first || !top.contains(document.activeElement))) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  },

  onClick(e) {
    const opener = e.target.closest && e.target.closest('[data-modal-open]');
    if (opener) {
      JackilModal.open(opener.getAttribute('data-modal-open'), opener);
      return;
    }
    if (e.target.closest && e.target.closest('[data-modal-close]')) {
      JackilModal.close();
      return;
    }
    const top = this.stack[this.stack.length - 1];
    if (top && !this.stack.some((el) => el !== top && el.contains(e.target))) {
      // A click outside the inner .modal is a dismissal, but never when it
      // came from inside one.
      const modal = top.querySelector('.modal');
      if (modal && modal.contains(e.target)) return;
    }
    if (e.target === top) this.close();
  },

  /* ── Promise dialogs ─────────────────────────────────────────────────── */

  _ensureDialog(id, inner) {
    const existing = document.getElementById(id);
    if (existing) return existing;
    document.body.insertAdjacentHTML(
      'beforeend',
      `<div class="modal-overlay" id="${id}" aria-hidden="true"><div class="modal">${inner}</div></div>`,
    );
    return document.getElementById(id);
  },

  /* One rule for both: the answer arrives from exactly one of four places —
     the confirm button, the cancel button, Enter in the field, or a dismissal
     routed through close() — and whichever it is settles the promise once.
     `onAnswer` gets null on Enter so a dialog can tell a click from a keypress
     when true/false is what it returns. */
  _dialog(id, inner, words, onAnswer) {
    const el = this._ensureDialog(id, inner);
    // The wording and the confirm button's colour change per call while the
    // overlay itself is reused, so they are written with textContent and
    // className — never interpolated into markup.
    this._text[id] = (root) => {
      const title = root.querySelector('.modal-title');
      if (title) title.textContent = words.title;
      const bodyText = root.querySelector('[data-dialog-text]');
      if (bodyText) bodyText.textContent = words.body || '';
      const field = root.querySelector('[data-dialog-value]');
      if (field) {
        field.value = words.value || '';
        if ('placeholder' in words) field.placeholder = words.placeholder;
      }
      const ok = root.querySelector('[data-dialog="ok"]');
      if (ok) {
        ok.textContent = words.confirmText;
        ok.className = `btn ${words.danger ? 'btn-rose' : 'btn-mint'}`;
      }
    };
    return new Promise((resolve) => {
      let settled = false;
      const finish = (value) => {
        if (settled) return;
        settled = true;
        delete this._cancellers[id];
        this.close();
        resolve(value);
      };
      // Escape and a scrim click never reach a handler on this side; close()
      // looks the hook up instead. "Answered nothing" is the same value as
      // Cancel, so no caller can hang on a dialog the operator dismissed.
      this._cancellers[id] = () => finish(onAnswer(null, el, true));
      this._all('[data-dialog]', el).forEach((btn) => {
        btn.onclick = () => finish(onAnswer(btn, el, false));
      });
      const field = el.querySelector('[data-dialog-value]');
      if (field) {
        field.onkeydown = (e) => {
          if (e.key !== 'Enter') return;
          e.preventDefault();
          finish(onAnswer(null, el, false));
        };
      }
      this.open(id);
    });
  },

  /* Resolves the trimmed text someone typed, or null for an empty answer —
     so "OK with nothing in the box" and "cancelled" are one outcome, which is
     what every caller here wants. */
  prompt(title, opts) {
    const o = opts || {};
    return this._dialog(
      'jm-prompt',
      `<div class="modal-header"><div class="modal-title"></div></div>
       <div class="modal-body"><input type="text" class="form-input" data-dialog-value autocomplete="off"></div>
       <div class="modal-footer">
         <button type="button" class="btn btn-outline" data-dialog="cancel">Cancel</button>
         <button type="button" class="btn btn-mint" data-dialog="ok"></button>
       </div>`,
      { title, value: o.value || '', placeholder: o.placeholder || '', confirmText: o.confirmText || 'OK' },
      (_btn, root) => {
        const field = root.querySelector('[data-dialog-value]');
        return (field && field.value.trim()) || null;
      },
    );
  },

  confirm(text, opts) {
    const o = opts || {};
    return this._dialog(
      'jm-confirm',
      `<div class="modal-header"><div class="modal-title"></div></div>
       <div class="modal-body"><p class="dialog-text" data-dialog-text></p></div>
       <div class="modal-footer">
         <button type="button" class="btn btn-outline" data-dialog="cancel">Cancel</button>
         <button type="button" class="btn btn-mint" data-dialog="ok"></button>
       </div>`,
      { title: text, confirmText: o.confirmText || 'OK', danger: !!o.danger },
      (btn) => Boolean(btn) && btn.dataset.dialog === 'ok',
    );
  },
};

document.addEventListener('keydown', (e) => JackilModal.handleKeydown(e));
document.addEventListener('click', (e) => JackilModal.onClick(e));
