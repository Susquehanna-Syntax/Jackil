/* Dynamic Links panel — the chips, their removal, and the Add link dialog.
 *
 * The server renders an empty shell ({% links_panel %}); this fills it from
 * /links/for/<type>/<id>/, so one client serves every registered type.
 */

//: Tone → accent pastel, matching TONE_PASTEL in jackil-widgets.js. Where
//: colour carries meaning the same state is also written in words.
const LINKS_TONE_PASTEL = { ok: 'mint', warn: 'lemon', bad: 'rose', info: 'sky' };

const LINKS_DEFAULT_RELATION = 'relates_to';

//: A pasted link is an absolute URL or a path into this app; resolve-url
//: recognises both forms.
const LINKS_URL_SHAPE = /^https?:\/\//;

//: One dialog for every panel on the page: it is rebuilt per open, so pages
//: with several panels don't each get their own copy of the same form.
const JackilLinks = {
  DIALOG_ID: 'jackil-links-dialog',
  panel: null,
  timer: null,
  token: 0,

  looksLikeLink(value) {
    return LINKS_URL_SHAPE.test(value) || value.startsWith('/');
  },

  /* ── Panel ───────────────────────────────────────────────────────────── */

  bind(panel) {
    const state = { relations: [] };
    panel.jackilLinks = state;

    panel.querySelector('[data-links-groups]').addEventListener('click', (e) => {
      const remove = e.target.closest('.link-chip-remove');
      if (remove) this.removeLink(panel, remove.closest('.link-chip').dataset.linkId);
    });
    const addBtn = panel.querySelector('[data-links-add]');
    if (addBtn) addBtn.addEventListener('click', () => this.openDialog(panel));
    this.load(panel);
  },

  load(panel) {
    return apiJson('/links/for/' + encodeURIComponent(panel.dataset.type) + '/'
      + encodeURIComponent(panel.dataset.id) + '/')
      .then((data) => {
        panel.jackilLinks.relations = data.relations || [];
        this.paint(panel, data.links || []);
      })
      .catch(() => {
        this.groups(panel).innerHTML = '<span class="muted-note">Links could not be loaded.</span>';
      });
  },

  paint(panel, links) {
    this.groups(panel).innerHTML = links.length ? this.chipsHtml(links)
      : '<span class="muted-note">Nothing linked yet.</span>';
  },

  groups(panel) {
    return panel.querySelector('[data-links-groups]');
  },

  chipsHtml(links) {
    // One group per relation label, in the order the service returned them —
    // that order is RELATIONS' own, so the panel reads the same on every page.
    const order = [];
    const byLabel = new Map();
    links.forEach((link) => {
      if (!byLabel.has(link.label)) {
        byLabel.set(link.label, []);
        order.push(link.label);
      }
      byLabel.get(link.label).push(this.chipHtml(link));
    });
    return order.map((label) =>
      '<div class="links-group">'
      + '<div class="links-group-label">' + escHtml(label) + '</div>'
      + '<div class="links-group-chips">' + byLabel.get(label).join('') + '</div>'
      + '</div>',
    ).join('');
  },

  chipHtml(link) {
    const other = link.other || {};
    const name = String(other.label || other.id || '');
    const classes = ['link-chip'];
    const pastel = LINKS_TONE_PASTEL[other.tone] || '';
    if (pastel) classes.push('tc-' + pastel);
    if (other.available === false) classes.push('unavailable');
    const titled = other.url
      ? '<a href="' + escAttr(other.url) + '">' + escHtml(name) + '</a>'
      : '<span>' + escHtml(name) + '</span>';
    return '<span class="' + classes.join(' ') + '" data-link-id="' + escAttr(link.link_id) + '">'
      // The group heading already says the relation; the chip names the thing.
      + titled
      + (other.status ? '<span class="link-chip-status">' + escHtml(other.status) + '</span>' : '')
      + '<button type="button" class="link-chip-remove" aria-label="'
      + escAttr('Remove link to ' + name) + '">&times;</button>'
      + '</span>';
  },

  removeLink(panel, linkId) {
    JackilModal.confirm('Remove this link?', { confirmText: 'Remove', danger: true }).then((yes) => {
      if (!yes) return;
      apiJson('/links/' + encodeURIComponent(linkId) + '/remove/', { method: 'POST' })
        .then(() => {
          showToast('Link removed');
          return this.load(panel);
        })
        .catch((err) => showToast(err.message, 'error'));
    });
  },

  /* ── Add link dialog ─────────────────────────────────────────────────── */

  ensureDialog() {
    const existing = document.getElementById(this.DIALOG_ID);
    if (existing) return existing;
    document.body.insertAdjacentHTML(
      'beforeend',
      '<div class="modal-overlay" id="' + this.DIALOG_ID + '" aria-hidden="true"><div class="modal">'
      + '<div class="modal-header"><div class="modal-title">Add link</div></div>'
      + '<div class="modal-body">'
      + '<div class="form-group"><label class="form-label" for="links_query">Find something</label>'
      + '<input type="text" class="form-input" id="links_query" data-links-query autocomplete="off" '
      + 'role="combobox" aria-controls="links_results" aria-expanded="false" '
      + 'placeholder="Search tickets, issues, pages, items&hellip; or paste a link"></div>'
      + '<div class="form-group"><label class="form-label" for="links_relation">Relation</label>'
      + '<select class="form-select" id="links_relation" data-links-relation></select></div>'
      + '<div class="links-results" id="links_results" role="listbox" data-links-results>'
      + '<span class="muted-note">Start typing.</span></div>'
      + '<div class="links-keys muted-note">Arrow keys to move, Enter to link.</div>'
      + '</div>'
      + '<div class="modal-footer"><button type="button" class="btn btn-outline" data-modal-close>Cancel</button></div>'
      + '</div></div>',
    );
    const el = document.getElementById(this.DIALOG_ID);
    const query = el.querySelector('[data-links-query]');
    query.addEventListener('input', (e) => this.onType(e.target.value));
    query.addEventListener('keydown', (e) => this.onKey(e));
    el.querySelector('[data-links-results]').addEventListener('click', (e) => {
      const row = e.target.closest('[data-links-result]');
      if (row) this.addTarget(row);
    });
    return el;
  },

  openDialog(panel) {
    this.panel = panel;
    const el = this.ensureDialog();
    const relations = panel.jackilLinks.relations.length
      ? panel.jackilLinks.relations
      : [[LINKS_DEFAULT_RELATION, 'relates to', 'relates to']];
    el.querySelector('[data-links-relation]').innerHTML = relations.map((rel) =>
      '<option value="' + escAttr(rel[0]) + '"'
      + (rel[0] === LINKS_DEFAULT_RELATION ? ' selected' : '') + '>'
      + escHtml(rel[1]) + '</option>',
    ).join('');
    el.querySelector('[data-links-query]').value = '';
    this.results(el).innerHTML = '<span class="muted-note">Start typing.</span>';
    JackilModal.open(this.DIALOG_ID, panel.querySelector('[data-links-add]'));
  },

  results(el) {
    return (el || document.getElementById(this.DIALOG_ID)).querySelector('[data-links-results]');
  },

  note(message) {
    this.active = -1;
    this.results().innerHTML = '<span class="muted-note">' + escHtml(message) + '</span>';
  },

  onType(value) {
    clearTimeout(this.timer);
    const term = value.trim();
    const token = ++this.token;
    if (!term) {
      this.note('Start typing.');
      return;
    }
    // The dialog is one node reused across opens and keystrokes, so only the
    // most recent answer may paint — a slow search must not overwrite the
    // results of a newer one.
    this.timer = setTimeout(() => {
      if (token !== this.token) return;
      const isLink = this.looksLikeLink(term);
      if (!isLink && term.length < 2) {
        this.note('Keep typing…');
        return;
      }
      this.note('Searching…');
      apiJson(this.searchUrl(term, isLink))
        .then((data) => {
          if (token !== this.token) return;
          this.renderResults(isLink ? [data.target] : data.results || []);
        })
        .catch((err) => {
          if (token !== this.token) return;
          this.note(err.message);
        });
    }, 250);
  },

  searchUrl(term, isLink) {
    if (isLink) return '/links/resolve-url/?url=' + encodeURIComponent(term);
    const params = new URLSearchParams({ q: term });
    params.set('exclude_type', this.panel.dataset.type);
    params.set('exclude_id', this.panel.dataset.id);
    return '/links/search/?' + params.toString();
  },

  renderResults(results) {
    if (!results.length) {
      this.note('Nothing found.');
      return;
    }
    // Grouped under the type's own words, in the order the search returned
    // them, so "Issues" and "Vigil hosts" read as headings, not as codes.
    const groups = new Map();
    results.forEach((target) => {
      const key = target.type_label || target.type;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(target);
    });
    let html = '';
    groups.forEach((targets, heading) => {
      html += '<div class="links-result-group">' + escHtml(heading) + '</div>';
      html += targets.map((target) =>
        '<button type="button" class="links-result" role="option" tabindex="-1" data-links-result'
        + ' data-type="' + escAttr(target.type) + '" data-id="' + escAttr(target.id) + '">'
        + '<span class="links-result-label">' + escHtml(target.label) + '</span>'
        + (target.status ? '<small>' + escHtml(target.status) + '</small>' : '')
        + '</button>',
      ).join('');
    });
    this.results().innerHTML = html;
    this.setActive(0);
  },

  rows() {
    return Array.from(this.results().querySelectorAll('[data-links-result]'));
  },

  setActive(index) {
    const rows = this.rows();
    rows.forEach((row, i) => row.classList.toggle('active', i === index));
    this.active = rows.length ? index : -1;
    if (rows[index]) rows[index].scrollIntoView({ block: 'nearest' });
    const query = document.getElementById('links_query');
    if (query) query.setAttribute('aria-expanded', rows.length ? 'true' : 'false');
  },

  onKey(e) {
    const rows = this.rows();
    if (!rows.length) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const step = e.key === 'ArrowDown' ? 1 : -1;
      this.setActive((this.active + step + rows.length) % rows.length);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (rows[this.active]) this.addTarget(rows[this.active]);
    }
  },

  addTarget(row) {
    const dialog = document.getElementById(this.DIALOG_ID);
    const panel = this.panel;
    const body = JSON.stringify({
      source_type: panel.dataset.type,
      source_id: panel.dataset.id,
      target_type: row.dataset.type,
      target_id: row.dataset.id,
      relation: dialog.querySelector('[data-links-relation]').value,
    });
    apiJson('/links/add/', { method: 'POST', body: body })
      .then(() => {
        JackilModal.close();
        showToast('Linked');
        return this.load(panel);
      })
      // A refused link is the dialog's own business: it stays open with the
      // server's words beside what was just clicked.
      .catch((err) => {
        this.results().insertAdjacentHTML(
          'afterbegin',
          '<span class="muted-note">' + escHtml(err.message) + '</span>',
        );
      });
  },
};

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-links-panel]').forEach((panel) => JackilLinks.bind(panel));
});
