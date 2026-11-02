/* Help center: search as you type under the hero, the form chooser's filter,
 * and (staff only) arranging which forms and help sections are pinned.
 */

const JackilHelp = {
  /* ── Search as you type ─────────────────────────────────────────────── */

  initSearch(form) {
    const input = form.querySelector('input[name="q"]');
    const box = form.querySelector('.hc-results');
    let timer = null;
    let token = 0;

    const close = () => {
      box.hidden = true;
      input.setAttribute('aria-expanded', 'false');
    };
    const paint = (data, term) => {
      const guides = data.guides || [];
      const forms = data.forms || [];
      const ticket = form.dataset.ticket + '?title=' + encodeURIComponent(term);
      let html = '';
      if (guides.length) {
        html += '<div class="hc-group">Guides</div>' + guides.map((g) =>
          '<a class="hc-hit" role="option" href="' + escAttr(g.url) + '">' + escHtml(g.title)
          + '<small>' + escHtml(g.space) + '</small></a>').join('');
      }
      if (forms.length) {
        html += '<div class="hc-group">Forms</div>' + forms.map((f) =>
          '<a class="hc-hit" role="option" href="' + escAttr(f.url) + '">' + escHtml(f.name)
          + '<small>Fill out a form</small></a>').join('');
      }
      html += (guides.length || forms.length)
        ? '<div class="hc-group">Not it?</div>'
        : '<div class="hc-none-hit">Nothing matches yet.</div>';
      html += '<a class="hc-hit hc-hit-ticket" role="option" href="' + escAttr(ticket) + '">'
        + 'Open a ticket about &ldquo;' + escHtml(term) + '&rdquo;</a>';
      box.innerHTML = html;
      box.hidden = false;
      input.setAttribute('aria-expanded', 'true');
    };

    input.addEventListener('input', () => {
      clearTimeout(timer);
      const term = input.value.trim();
      const mine = ++token;
      if (term.length < 2) { close(); return; }
      timer = setTimeout(() => {
        fetch(form.dataset.suggest + '?q=' + encodeURIComponent(term), { credentials: 'same-origin' })
          .then((r) => (r.ok ? r.json() : { guides: [], forms: [] }))
          .then((data) => { if (mine === token) paint(data, term); })
          .catch(() => {});
      }, 200);
    });
    input.addEventListener('keydown', (e) => {
      const hits = Array.from(box.querySelectorAll('.hc-hit'));
      if (e.key === 'Escape') { close(); return; }
      if (!hits.length || !['ArrowDown', 'ArrowUp'].includes(e.key)) return;
      e.preventDefault();
      const at = hits.indexOf(document.activeElement);
      hits[(at + (e.key === 'ArrowDown' ? 1 : -1) + hits.length) % hits.length].focus();
    });
    box.addEventListener('keydown', (e) => {
      if (!['ArrowDown', 'ArrowUp'].includes(e.key)) return;
      e.preventDefault();
      const hits = Array.from(box.querySelectorAll('.hc-hit'));
      const at = hits.indexOf(document.activeElement);
      const next = at + (e.key === 'ArrowDown' ? 1 : -1);
      if (next < 0) input.focus(); else hits[next % hits.length].focus();
    });
    document.addEventListener('click', (e) => { if (!form.contains(e.target)) close(); });
  },

  initFormFilter(input) {
    const rows = Array.from(document.querySelectorAll('[data-hc-formrow]'));
    input.addEventListener('input', () => {
      const term = input.value.trim().toLowerCase();
      rows.forEach((row) => { row.hidden = term && !row.textContent.toLowerCase().includes(term); });
    });
  },

  /* ── Arranging (staff) ──────────────────────────────────────────────── */

  initArrange(root) {
    const toggle = root.querySelector('[data-hc-arrange]');
    if (!toggle) return;
    let dragging = null;

    const lists = () => Array.from(root.querySelectorAll('[data-hc-list]'));
    const setMode = (on) => {
      root.classList.toggle('hc-arranging', on);
      toggle.setAttribute('aria-pressed', on ? 'true' : 'false');
      toggle.textContent = on ? 'Done arranging' : 'Arrange';
      root.querySelectorAll('[data-pin]').forEach((card) => { card.draggable = on; });
    };
    toggle.addEventListener('click', () => setMode(!root.classList.contains('hc-arranging')));

    root.addEventListener('click', (e) => {
      if (!root.classList.contains('hc-arranging')) return;
      const unpin = e.target.closest('.hc-unpin');
      const card = e.target.closest('[data-pin]');
      if (unpin && card) { e.preventDefault(); card.remove(); return; }
      // While arranging, a card is something to move, not a link to follow.
      if (card) e.preventDefault();
    });

    root.addEventListener('dragstart', (e) => {
      dragging = e.target.closest('[data-pin]');
      if (dragging) { dragging.classList.add('hc-dragging'); e.dataTransfer.effectAllowed = 'move'; }
    });
    root.addEventListener('dragend', () => {
      if (dragging) dragging.classList.remove('hc-dragging');
      dragging = null;
    });
    lists().forEach((list) => {
      list.addEventListener('dragover', (e) => {
        if (!dragging || dragging.parentElement !== list) return;
        e.preventDefault();
        const over = e.target.closest('[data-pin]');
        if (!over || over === dragging) return;
        const box = over.getBoundingClientRect();
        const after = (e.clientY - box.top) / box.height > 0.5 || (e.clientX - box.left) / box.width > 0.5;
        list.insertBefore(dragging, after ? over.nextSibling : over);
      });
    });

    root.querySelectorAll('[data-hc-add]').forEach((select) => {
      select.addEventListener('change', () => {
        const value = select.value;
        if (!value) return;
        const label = select.selectedOptions[0].textContent;
        const list = root.querySelector('[data-hc-list="' + select.dataset.hcAdd + '"]');
        const empty = list.querySelector('.hc-none');
        if (empty) empty.remove();
        const card = document.createElement(select.dataset.hcAdd === 'forms' ? 'a' : 'div');
        card.className = select.dataset.hcAdd === 'forms' ? 'hc-form tc-lav' : 'hc-topic tc-lav';
        card.dataset.pin = value;
        card.draggable = true;
        card.innerHTML = '<b>' + escHtml(label) + '</b><span class="hc-go">Saved on Save</span>'
          + '<button type="button" class="hc-unpin" aria-label="Unpin ' + escAttr(label) + '">&times;</button>';
        list.appendChild(card);
        select.selectedOptions[0].remove();
        select.value = '';
      });
    });

    root.querySelector('[data-hc-save]').addEventListener('click', () => {
      const ids = (name) => Array.from(root.querySelectorAll('[data-hc-list="' + name + '"] [data-pin]'))
        .map((card) => card.dataset.pin);
      apiJson(root.dataset.pinsUrl, {
        method: 'POST',
        body: JSON.stringify({ forms: ids('forms'), spaces: ids('spaces') }),
      })
        .then(() => {
          showToast('Saved. Customers see this order now.');
          window.location.reload();
        })
        .catch((err) => showToast(err.message || 'Could not save', 'error'));
    });
  },
};

document.querySelectorAll('[data-hc-search]').forEach((form) => JackilHelp.initSearch(form));
document.querySelectorAll('[data-hc-formfilter]').forEach((input) => JackilHelp.initFormFilter(input));
document.querySelectorAll('[data-hc-root]').forEach((root) => JackilHelp.initArrange(root));
