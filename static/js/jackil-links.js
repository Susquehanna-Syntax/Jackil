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
  previewToken: 0,
  tabs: null,
  tab: '',
  selected: null,

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
  //
  // How it is related comes first (a dropdown, so the vocabulary can grow),
  // then one coloured tab per type. Each tab lists recent things before
  // anything is typed and searches only its own type; the selected result is
  // previewed on the right before anything is linked.

  ensureDialog() {
    const existing = document.getElementById(this.DIALOG_ID);
    if (existing) return existing;
    document.body.insertAdjacentHTML(
      'beforeend',
      '<div class="modal-overlay" id="' + this.DIALOG_ID + '" aria-hidden="true">'
      + '<div class="modal link-picker" role="dialog" aria-modal="true" aria-labelledby="links_title">'
      + '<div class="modal-header"><div class="modal-title" id="links_title">Add link</div>'
      + '<button type="button" class="modal-close" data-modal-close aria-label="Close">'
      + '<svg viewBox="0 0 24 24"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>'
      + '</button></div>'
      + '<div class="lp-step"><label class="lp-label" for="links_relation">How is it related?</label>'
      + '<select class="form-select lp-relation" id="links_relation" data-links-relation></select></div>'
      + '<div class="lp-step lp-step-tight"><span class="lp-label">What it links to</span></div>'
      + '<div class="tab-bar lp-tabs" role="tablist" aria-label="What it links to" data-lp-tabs></div>'
      + '<div class="lp-body">'
      + '<div class="lp-left">'
      + '<input type="text" class="form-input" id="links_query" data-links-query autocomplete="off" '
      + 'role="combobox" aria-controls="links_results" aria-expanded="false" '
      + 'placeholder="Search, or paste a link">'
      + '<div class="links-results" id="links_results" role="listbox" data-links-results></div>'
      + '<div class="links-keys muted-note">Arrow keys to move, Enter to link.</div>'
      + '</div>'
      + '<div class="lp-right" data-lp-preview aria-live="polite"></div>'
      + '</div>'
      + '<div class="modal-footer lp-foot"><span class="lp-sum" data-lp-sum></span>'
      + '<span class="lp-actions"><button type="button" class="btn btn-outline" data-modal-close>Cancel</button>'
      + '<button type="button" class="btn btn-lav" data-lp-link disabled>Link</button></span></div>'
      + '</div></div>',
    );
    const el = document.getElementById(this.DIALOG_ID);
    const query = el.querySelector('[data-links-query]');
    query.addEventListener('input', (e) => this.onType(e.target.value));
    query.addEventListener('keydown', (e) => this.onKey(e));
    el.querySelector('[data-links-results]').addEventListener('click', (e) => {
      const row = e.target.closest('[data-links-result]');
      if (row) this.setActive(this.rows().indexOf(row));
    });
    el.querySelector('[data-links-results]').addEventListener('dblclick', (e) => {
      if (e.target.closest('[data-links-result]')) this.addSelected();
    });
    el.querySelector('[data-lp-tabs]').addEventListener('click', (e) => {
      const tab = e.target.closest('[data-lp-type]');
      if (tab) this.selectTab(tab.dataset.lpType);
    });
    el.querySelector('[data-links-relation]').addEventListener('change', () => this.paintSummary());
    el.querySelector('[data-lp-link]').addEventListener('click', () => this.addSelected());
    return el;
  },

  openDialog(panel) {
    this.panel = panel;
    this.selected = null;
    const el = this.ensureDialog();
    const relations = panel.jackilLinks.relations.length
      ? panel.jackilLinks.relations
      : [[LINKS_DEFAULT_RELATION, 'relates to', 'relates to']];
    el.querySelector('[data-links-relation]').innerHTML = relations.map((rel) =>
      '<option value="' + escAttr(rel[0]) + '"'
      + (rel[0] === LINKS_DEFAULT_RELATION ? ' selected' : '') + '>'
      + escHtml(rel[1].charAt(0).toUpperCase() + rel[1].slice(1)) + '</option>',
    ).join('');
    el.querySelector('[data-links-query]').value = '';
    this.paintPreview(null);
    JackilModal.open(this.DIALOG_ID, panel.querySelector('[data-links-add]'));
    el.querySelector('[data-links-relation]').focus();
    this.loadTabs().then(() => {
      const first = (this.tabs || []).find((t) => t.available && !t.name.startsWith('vigil:'))
        || (this.tabs || [])[0];
      if (first) this.selectTab(this.tab && this.tabs.some((t) => t.name === this.tab) ? this.tab : first.name);
    });
  },

  loadTabs() {
    return apiJson('/links/types/')
      .then((data) => {
        this.tabs = data.types || [];
        const bar = document.querySelector('#' + this.DIALOG_ID + ' [data-lp-tabs]');
        bar.innerHTML = this.tabs.map((t) =>
          '<button type="button" class="tab t-' + escAttr(t.colour || 'all') + '" role="tab"'
          + ' data-lp-type="' + escAttr(t.name) + '" aria-selected="false">'
          + escHtml(t.name.startsWith('vigil:') ? t.label.replace(/^Vigil (\w)/, (m, c) => c.toUpperCase()) : t.label)
          + (t.name.startsWith('vigil:') ? ' <span class="tab-note">from Vigil</span>' : '')
          + '</button>',
        ).join('');
      })
      .catch(() => {
        this.tabs = [];
        this.note('Link types could not be loaded.');
      });
  },

  tabInfo(name) {
    return (this.tabs || []).find((t) => t.name === name) || { name: name, label: name, colour: 'all' };
  },

  selectTab(name) {
    this.tab = name;
    document.querySelectorAll('#' + this.DIALOG_ID + ' [data-lp-type]').forEach((tab) => {
      tab.setAttribute('aria-selected', tab.dataset.lpType === name ? 'true' : 'false');
    });
    const info = this.tabInfo(name);
    const query = document.getElementById('links_query');
    query.placeholder = 'Search ' + info.label.toLowerCase() + ', or paste a link';
    this.selected = null;
    this.paintPreview(null);
    this.onType(query.value, true);
    query.focus();
  },

  results(el) {
    return (el || document.getElementById(this.DIALOG_ID)).querySelector('[data-links-results]');
  },

  note(message) {
    this.active = -1;
    this.results().innerHTML = '<span class="muted-note">' + escHtml(message) + '</span>';
  },

  onType(value, now) {
    clearTimeout(this.timer);
    const term = value.trim();
    const token = ++this.token;
    // The dialog is one node reused across opens and keystrokes, so only the
    // most recent answer may paint — a slow search must not overwrite the
    // results of a newer one.
    this.timer = setTimeout(() => {
      if (token !== this.token) return;
      const isLink = this.looksLikeLink(term);
      if (!isLink && term.length === 1) {
        this.note('Keep typing…');
        return;
      }
      apiJson(this.searchUrl(term, isLink))
        .then((data) => {
          if (token !== this.token) return;
          if (isLink) {
            this.renderResults([data.target]);
          } else if (data.available === false) {
            this.note(this.tab.startsWith('vigil:') ? 'Vigil unavailable right now.' : 'Unavailable right now.');
          } else {
            this.renderResults(data.results || [], term);
          }
        })
        .catch((err) => {
          if (token !== this.token) return;
          this.note(err.message);
        });
    }, now ? 0 : 250);
  },

  searchUrl(term, isLink) {
    if (isLink) return '/links/resolve-url/?url=' + encodeURIComponent(term);
    const params = new URLSearchParams({ type: this.tab, q: term });
    params.set('exclude_type', this.panel.dataset.type);
    params.set('exclude_id', this.panel.dataset.id);
    return '/links/search/?' + params.toString();
  },

  renderResults(results, term) {
    if (!results.length) {
      this.note(term ? 'Nothing found.' : 'Nothing here yet. Type to search.');
      this.paintPreview(null);
      return;
    }
    this.results().innerHTML = results.map((target) => {
      const colour = this.tabInfo(target.type).colour || 'all';
      const dot = target.type.startsWith('vigil:') && target.status
        ? '<span class="lp-dot ' + (target.tone === 'ok' ? 'on' : 'off') + '" aria-hidden="true"></span>' : '';
      return '<button type="button" class="links-result lp-result tc-' + escAttr(colour) + '" role="option"'
        + ' tabindex="-1" aria-selected="false" data-links-result'
        + ' data-type="' + escAttr(target.type) + '" data-id="' + escAttr(target.id) + '"'
        + ' data-label="' + escAttr(target.label) + '">'
        + '<span class="lp-icon" aria-hidden="true">' + escHtml(String(target.label || '?').replace(/^#/, '').charAt(0).toUpperCase()) + '</span>'
        + '<span class="lp-text"><span class="links-result-label">' + escHtml(target.label) + '</span>'
        + (target.status ? '<small>' + escHtml(target.status) + '</small>' : '') + '</span>'
        + dot
        + '</button>';
    }).join('');
    this.setActive(0);
  },

  rows() {
    return Array.from(this.results().querySelectorAll('[data-links-result]'));
  },

  setActive(index) {
    const rows = this.rows();
    rows.forEach((row, i) => {
      row.classList.toggle('active', i === index);
      row.setAttribute('aria-selected', i === index ? 'true' : 'false');
    });
    this.active = rows.length ? index : -1;
    const query = document.getElementById('links_query');
    if (query) query.setAttribute('aria-expanded', rows.length ? 'true' : 'false');
    const row = rows[index];
    if (!row) return;
    row.scrollIntoView({ block: 'nearest' });
    this.selected = { type: row.dataset.type, id: row.dataset.id, label: row.dataset.label };
    this.paintSummary();
    this.loadPreview(this.selected);
  },

  loadPreview(sel) {
    const token = ++this.previewToken;
    apiJson('/links/preview/' + encodeURIComponent(sel.type) + '/' + encodeURIComponent(sel.id) + '/')
      .then((data) => {
        if (token === this.previewToken) this.paintPreview(data);
      })
      .catch(() => {
        if (token === this.previewToken) this.paintPreview({ target: sel, links: [], failed: true });
      });
  },

  paintPreview(data) {
    const pane = document.querySelector('#' + this.DIALOG_ID + ' [data-lp-preview]');
    const linkBtn = document.querySelector('#' + this.DIALOG_ID + ' [data-lp-link]');
    if (linkBtn) linkBtn.disabled = !this.selected;
    if (!pane) return;
    pane.className = 'lp-right';
    if (!data) {
      pane.innerHTML = '<span class="muted-note">Pick something to see it here before you link it.</span>';
      this.paintSummary();
      return;
    }
    const t = data.target || {};
    const colour = t.colour || this.tabInfo(t.type).colour || 'all';
    pane.classList.add('tc-' + colour);
    const kind = String(t.type_label || this.tabInfo(t.type).label || '').replace(/s$/, '');
    const facts = (t.facts || []).map((f) =>
      '<div class="lp-fact"><span>' + escHtml(f[0]) + '</span><b>' + escHtml(f[1]) + '</b></div>',
    ).join('');
    const linked = (data.links || []).map((l) =>
      '<span class="lp-linked">' + escHtml(l.label) + ' ' + escHtml((l.other || {}).label || '') + '</span>',
    ).join('');
    pane.innerHTML = '<div class="lp-preview">'
      + '<div class="lp-kind">' + escHtml(kind) + '</div>'
      + '<h3 class="lp-title">' + escHtml(t.label || '') + '</h3>'
      + (t.status ? '<div class="lp-status">' + escHtml(t.status) + '</div>' : '')
      + (data.failed ? '<p class="muted-note">The preview could not be loaded.</p>' : '')
      + (t.excerpt ? '<p class="lp-excerpt">' + escHtml(t.excerpt) + '</p>' : '')
      + (facts ? '<div class="lp-facts">' + facts + '</div>' : '')
      + (linked ? '<div class="lp-also"><span class="lp-also-label">Already linked</span>' + linked + '</div>' : '')
      + (t.url && /^(https?:\/\/|\/(?!\/))/.test(t.url) ? '<a class="lp-open" href="' + escAttr(t.url) + '" target="_blank" rel="noopener">Open in a new tab</a>' : '')
      + '</div>';
  },

  paintSummary() {
    const sum = document.querySelector('#' + this.DIALOG_ID + ' [data-lp-sum]');
    if (!sum) return;
    const select = document.querySelector('#' + this.DIALOG_ID + ' [data-links-relation]');
    const words = select && select.selectedOptions[0] ? select.selectedOptions[0].textContent.toLowerCase() : '';
    sum.innerHTML = this.selected
      ? 'This <b>' + escHtml(words) + '</b> ' + escHtml(this.selected.label)
      : '';
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
      this.addSelected();
    }
  },

  addSelected() {
    if (!this.selected) return;
    const dialog = document.getElementById(this.DIALOG_ID);
    const panel = this.panel;
    const body = JSON.stringify({
      source_type: panel.dataset.type,
      source_id: panel.dataset.id,
      target_type: this.selected.type,
      target_id: this.selected.id,
      relation: dialog.querySelector('[data-links-relation]').value,
    });
    apiJson('/links/add/', { method: 'POST', body: body })
      .then(() => {
        JackilModal.close();
        showToast('Linked');
        return this.load(panel);
      })
      // A refused link is the dialog's own business: it stays open with the
      // server's words above the results.
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
