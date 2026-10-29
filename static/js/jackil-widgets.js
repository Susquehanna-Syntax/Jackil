/* Widget renderers — one function per contract shape.
 *
 * Every widget's data arrives from /dashboards/api/widgets/<kind>/data/ as a
 * versioned envelope (see apps/dashboards/contract.py), so the browser has
 * five renderers rather than one per widget kind. Each takes (body, data) —
 * the validated inner payload — and sets body.innerHTML.
 *
 * They run on first paint and again on the dashboard's refresh poll, so a
 * renderer must be safe to run repeatedly against the same element. A
 * renderer that throws is caught by paintWidget and its message shown in the
 * widget, so a broken one costs a tile rather than the grid.
 *
 * Every interpolated value goes through escHtml / escAttr: titles, names and
 * labels all carry ticket text entered by users.
 *
 * The file ends with the widget settings form — the dialog the Settings button
 * on each card opens. It is generated from the same registry the rail is
 * grouped by, so a widget added server-side gets a settings form without any
 * JavaScript changing.
 */

/* ── Shared helpers ────────────────────────────────────────────────────── */

//: Tone → SQSY accent. Pastels identify state; where colour carries meaning
//: the same state is also written in words. The contract's tone names map
//: onto vigil-dashboard.css's edge-* classes one for one.
const TONE_PASTEL = { ok: 'mint', warn: 'lemon', bad: 'rose', info: 'sky', muted: 'grey' };

//: Chart colours are the design language's comparison slots, used in a fixed
//: order — pastels identify, oc-* slots compare.
const SERIES_COLORS = ['var(--oc-1)', 'var(--oc-2)', 'var(--oc-3)', 'var(--oc-4)'];

function _tonePastel(tone) {
  return TONE_PASTEL[tone] || 'grey';
}

/* ── Renderers ─────────────────────────────────────────────────────────── */

function stat(body, data) {
  // A muted 0 is a placeholder ("Pick a project…", "Cost hidden"), not a
  // count: say the words, don't draw a big zero.
  if (data.tone === 'muted' && !data.value && !data.sub) {
    body.innerHTML = `<div class="dash-empty"><span class="muted-note">`
      + `${escHtml(data.label || 'Nothing to show')}</span></div>`;
    return;
  }
  const cls = 'dash-stat tc-' + _tonePastel(data.tone);
  const inner =
    `<div class="dash-stat-value">${escHtml(data.value)}</div>`
    + `<div class="dash-stat-label">${escHtml(data.label)}</div>`
    + (data.sub ? `<div class="dash-stat-sub">${escHtml(data.sub)}</div>` : '');
  body.innerHTML = data.href
    ? `<a class="${cls}" href="${escAttr(data.href)}">${inner}</a>`
    : `<div class="${cls}">${inner}</div>`;
}

function list(body, data) {
  const items = data.items || [];
  if (!items.length) {
    body.innerHTML = `<div class="dash-empty"><span class="muted-note">`
      + `${escHtml(data.empty || 'Nothing here yet')}</span></div>`;
    return;
  }
  // Row shape follows Vigil's _dashCard: a tinted card whose edge colour is
  // the row's tone, title and meta on the left, badge in the right column.
  const cards = items.map((item) => {
    const edge = 'edge-' + _tonePastel(item.tone);
    const main = `<div class="dash-card-main">`
      + `<div class="dash-card-title">${escHtml(item.title || '')}</div>`
      + (item.meta ? `<div class="dash-card-sub">${escHtml(item.meta)}</div>` : '')
      + `</div>`;
    const right = item.badge
      ? `<div class="dash-card-right">${escHtml(item.badge)}</div>`
      : '';
    const inner = main + right;
    const attrs = ` class="dash-card ${edge}" title="${escAttr(item.title || '')}"`;
    return item.href
      ? `<a href="${escAttr(item.href)}"${attrs}>${inner}</a>`
      : `<div${attrs}>${inner}</div>`;
  }).join('');
  body.innerHTML = `<div class="dash-cards">${cards}</div>`;
}

function table(body, data) {
  // A column is numeric if any row puts a number in it, so one column always
  // aligns the same way whatever the rows happen to hold.
  const numeric = (data.columns || []).map(() => false);
  const rows = data.rows || [];
  rows.forEach((row) => row.forEach((cell, j) => {
    if (typeof cell === 'number') numeric[j] = true;
  }));
  const head = `<thead><tr>${(data.columns || [])
    .map((c, j) => `<th${numeric[j] ? ' class="num"' : ''}>${escHtml(c)}</th>`).join('')}</tr></thead>`;
  const tbody = `<tbody>${rows.map((row) => `<tr>${row
    .map((cell, j) => `<td${numeric[j] ? ' class="num"' : ''}>${escHtml(cell)}</td>`)
    .join('')}</tr>`).join('')}</tbody>`;
  body.innerHTML = `<table class="dash-table">${head}${tbody}</table>`;
}

function gauge(body, data) {
  const hasValue = data.value !== null && data.value !== undefined;
  const pct = hasValue ? Math.max(0, Math.min(100, Number(data.value))) : 0;
  const r = 32;
  const circumference = 2 * Math.PI * r;
  const offset = circumference * (1 - pct / 100);
  const pastel = _tonePastel(data.tone);
  const text = hasValue ? Math.round(Number(data.value)) + '%' : '—';
  // The words below the ring carry the state on their own: colour is never
  // the only channel.
  body.innerHTML = `
    <div class="dash-gauge">
      <div class="dash-gauge-dial">
      <svg viewBox="0 0 78 78" class="dash-gauge-ring" aria-hidden="true">
        <circle cx="39" cy="39" r="${r}" class="gauge-bg"/>
        <circle cx="39" cy="39" r="${r}" stroke="var(--${pastel}-ink)"
                stroke-dasharray="${circumference.toFixed(1)}"
                stroke-dashoffset="${offset.toFixed(1)}" class="gauge-fill"/>
      </svg>
      <div class="dash-gauge-text">${escHtml(text)}</div>
      </div>
      <div class="dash-stat-label">${escHtml(data.label)}</div>
      ${data.sub ? `<div class="dash-stat-sub">${escHtml(data.sub)}</div>` : ''}
    </div>`;
}

/* ── Charts (inline SVG, no chart library) ─────────────────────────────── */

//: Drawn at the widget's real pixel size rather than stretched with
//: preserveAspectRatio="none": stretching distorts the axis type and every
//: mark with it. A ResizeObserver redraws when Gridstack resizes the cell.

function _legend(data) {
  if ((data.series || []).length < 2) return '';
  return `<div class="dash-legend">${(data.series || []).map((s, si) =>
    `<span><i style="background:${SERIES_COLORS[si % SERIES_COLORS.length]}"></i>`
    + `${escHtml(s.name)}</span>`).join('')}</div>`;
}

function _seriesSvg(data, W, H) {
  const labels = data.labels || [];
  const series = data.series || [];
  const values = series.flatMap((s) => s.values || []);
  // Stacked bars reach the sum of their segments, so that sum is the maximum
  // the y scale has to fit; every other kind peaks at a single value.
  const max = data.kind === 'stacked-bar'
    ? Math.max(...labels.map((_, li) => series.reduce((n, s) => n + ((s.values || [])[li] || 0), 0)), 0) || 1
    : Math.max(...values, 0) || 1;
  const padL = 30, padR = 6, padT = 6, padB = 18;
  const plotW = Math.max(10, W - padL - padR);
  const plotH = Math.max(10, H - padT - padB);
  const y = (v) => padT + (1 - v / max) * plotH;
  const colour = (i) => SERIES_COLORS[i % SERIES_COLORS.length];
  const parts = [];

  // Two gridlines with their values: zero and the maximum.
  for (const v of [0, max]) {
    parts.push(`<line x1="${padL}" x2="${W - padR}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" stroke="var(--grid-line)"/>`
      + `<text class="axis-text" x="${padL - 6}" y="${(y(v) + 3).toFixed(1)}" text-anchor="end">${escHtml(String(v))}</text>`);
  }

  let xOf;
  const isBar = data.kind === 'bar' || data.kind === 'stacked-bar';
  const groupW = plotW / Math.max(1, labels.length);
  if (isBar) {
    const stacked = data.kind === 'stacked-bar';
    const barW = stacked
      ? Math.max(1, groupW * 0.72)
      : Math.max(1, (groupW * 0.72) / Math.max(1, series.length));
    xOf = (i) => padL + groupW * i + groupW / 2;
    labels.forEach((label, li) => {
      const x0 = stacked ? xOf(li) - barW / 2 : padL + groupW * li + (groupW - barW * series.length) / 2;
      let stackTop = padT + plotH;
      series.forEach((s, si) => {
        const v = (s.values || [])[li] || 0;
        if (stacked && v <= 0) return;
        // One series: each bar is its own category, so it takes its own slot.
        const fill = stacked || series.length > 1 ? colour(si) : colour(li);
        let top = y(v);
        let height = padT + plotH - top;
        if (stacked) {
          stackTop -= (v / max) * plotH;
          top = stackTop;
          height = (v / max) * plotH;
        }
        const isTop = !stacked || si === series.length - 1
          || series.slice(si + 1).every((t) => ((t.values || [])[li] || 0) <= 0);
        const title = stacked ? `${label} · ${s.name || ''}: ${v}` : `${label}: ${v}`;
        parts.push(`<rect x="${(stacked ? x0 : x0 + si * barW).toFixed(1)}" y="${top.toFixed(1)}" `
          + `width="${barW.toFixed(1)}" height="${height.toFixed(1)}"`
          + (isTop ? ' rx="3"' : '') + ` fill="${fill}">`
          + `<title>${escHtml(title)}</title></rect>`);
      });
    });
  } else {
    const step = labels.length > 1 ? plotW / (labels.length - 1) : 0;
    xOf = (i) => padL + step * i;
    series.forEach((s, si) => {
      const vs = s.values || [];
      if (vs.length > 1) {
        const points = vs.map((v, i) => `${xOf(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
        if (data.kind === 'area') {
          parts.push(`<polygon fill="${colour(si)}" fill-opacity="0.18" stroke="none" `
            + `points="${points} ${xOf(vs.length - 1).toFixed(1)},${y(0).toFixed(1)} ${xOf(0).toFixed(1)},${y(0).toFixed(1)}"/>`);
        }
        parts.push(`<polyline fill="none" stroke="${colour(si)}" stroke-width="2" stroke-linejoin="round" `
          + `points="${points}"/>`);
      }
      vs.forEach((v, i) => parts.push(`<circle cx="${xOf(i).toFixed(1)}" cy="${y(v).toFixed(1)}" r="2.5" fill="${colour(si)}">`
        + `<title>${escHtml(`${labels[i] ?? ''}: ${v}`)}</title></circle>`));
    });
  }

  // Bars: every category keeps a label, cut to its slot with the full name on
  // hover, as long as a slot fits a few characters. Otherwise (and for lines)
  // as many labels as fit, evenly spaced, first and last always shown; a
  // label's width follows its length (an ISO date needs ~70px), and a label
  // too close to the always-shown last one gives way to it.
  const last = labels.length - 1;
  const slotChars = Math.floor((groupW - 6) / 6.5);
  if (isBar && slotChars >= 4) {
    labels.forEach((label, i) => {
      const full = String(label);
      const shown = full.length > slotChars ? full.slice(0, slotChars - 1) + '…' : full;
      parts.push(`<text class="axis-text" x="${xOf(i).toFixed(1)}" y="${H - 4}" text-anchor="middle">`
        + `<title>${escHtml(full)}</title>${escHtml(shown)}</text>`);
    });
  } else {
    const longest = labels.reduce((n, l) => Math.max(n, String(l).length), 0);
    const fit = Math.max(2, Math.floor(plotW / Math.max(56, longest * 6.5 + 12)) - 1);
    const every = Math.max(1, Math.ceil(labels.length / fit));
    labels.forEach((label, i) => {
      if (i !== last && (i % every !== 0 || last - i < every)) return;
      // The ends anchor inward so a long first or last label is never cut by
      // the plot's edge.
      const anchor = i === 0 ? 'start' : (i === last ? 'end' : 'middle');
      let x = xOf(i);
      if (isBar && i === 0) x = padL;
      if (isBar && i === last) x = W - padR;
      parts.push(`<text class="axis-text" x="${x.toFixed(1)}" y="${H - 4}" text-anchor="${anchor}">${escHtml(label)}</text>`);
    });
  }

  return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img">${parts.join('')}</svg>`;
}

function series(body, data) {
  const legend = _legend(data);
  body.innerHTML = `<div class="dash-series"><div class="dash-series-plot"></div>${legend}</div>`;
  const plot = body.querySelector('.dash-series-plot');
  const draw = () => {
    const W = Math.floor(plot.clientWidth), H = Math.floor(plot.clientHeight);
    if (W > 0 && H > 0) plot.innerHTML = _seriesSvg(data, W, H);
  };
  if (body._seriesObserver) body._seriesObserver.disconnect();
  if (window.ResizeObserver) {
    body._seriesObserver = new ResizeObserver(draw);
    body._seriesObserver.observe(plot);
  }
  draw();
}

/* ── Paint ─────────────────────────────────────────────────────────────── */

const WIDGET_SHAPES = {
  stat: stat,
  list: list,
  table: table,
  gauge: gauge,
  series: series,
};

/* Fetch one widget's data and hand the payload to its shape renderer. The
 * query string is the widget's own settings (minus the operator-set title,
 * which names the tile rather than selecting data); the server clamps and
 * ignores anything it does not know. */
async function paintWidget(body, widget) {
  const params = {};
  for (const [key, value] of Object.entries(widget.settings || {})) {
    if (key === 'title') continue;
    params[key] = value == null ? '' : String(value);
  }
  const url = '/dashboards/api/widgets/' + encodeURIComponent(widget.kind)
    + '/data/?' + new URLSearchParams(params);
  let payload;
  try {
    payload = await apiJson(url);
  } catch (e) {
    body.innerHTML = `<div class="dash-failed"><span class="muted-note">Couldn't load `
      + `this widget: ${escHtml(e.message || 'Request failed')}</span></div>`;
    return;
  }

  const render = WIDGET_SHAPES[payload.shape];
  if (!render) {
    body.innerHTML = `<div class="dash-failed"><span class="muted-note">Couldn't load `
      + `this widget: unknown shape ${escHtml(payload.shape)}</span></div>`;
    return;
  }
  try {
    render(body, payload.data || {});
  } catch (e) {
    body.innerHTML = `<div class="dash-failed"><span class="muted-note">Couldn't load `
      + `this widget: ${escHtml(e.message || 'Render failed')}</span></div>`;
    return;
  }
  // A report card carries its own title, which names the tile when the
  // operator hasn't typed one; a typed title always wins.
  if (payload.title && !(widget.settings || {}).title) {
    const item = body.closest('.grid-stack-item');
    const heading = item && item.querySelector('.dash-widget-title');
    if (heading) heading.textContent = payload.title;
  }
}

/* ── Widget settings form ──────────────────────────────────────────────── */

/* One builder for every field type the registry declares (see
   apps/dashboards/widgets.py), so the form a widget gets is exactly the schema
   it ships. Saving writes onto widget.settings in memory and marks the layout
   dirty; the values reach the server with the rest of the layout when edit
   mode ends — see _dashSaveLayout in jackil-dashboards.js. */
function _settingsField(name, field, value, options) {
  const id = `ws-${name}`;
  const label = `<label class="form-label" for="${escAttr(id)}">${escHtml(field.label || name)}</label>`;
  const t = field.type;

  if (t === 'bool') {
    // The checkbox carries its own words, so there is no separate label
    // element — and a .form-group margin would space it from its neighbours
    // twice over.
    return `<label class="setting-check">
      <input type="checkbox" id="${escAttr(id)}" data-setting="${escAttr(name)}"
             ${value ? 'checked' : ''}> ${escHtml(field.label || name)}</label>`;
  }
  if (t === 'int' || (t === 'saved_view' && !options.length)) {
    // A saved view *is* an id, so the number box is an honest fallback for it:
    // used when the options endpoint is unreachable and the picker has no list
    // to draw. The bounds are not decoration either — clean_settings clamps to
    // exactly these server-side, so a value outside them would be quietly
    // rewritten on save and the form would lie about what it stored. Hence the
    // explicit `!== undefined`: a declared min of 0 is a real bound, not an
    // absent one.
    const min = field.min !== undefined ? field.min : (t === 'saved_view' ? 0 : undefined);
    return `<div class="form-group">${label}
      <input type="number" class="form-input" id="${escAttr(id)}"
             data-setting="${escAttr(name)}" value="${escAttr(value ?? field.default ?? 0)}"
             ${min !== undefined ? `min="${escAttr(min)}"` : ''}
             ${field.max !== undefined ? `max="${escAttr(field.max)}"` : ''}></div>`;
  }
  // Only a saved-view, project or report-card picker has an options list to be
  // handed. A `choice` draws its own, and any other type drawing one would be
  // drawing it for a widget with no source of them.
  if ((t === 'saved_view' || t === 'project' || t === 'report_card') && options.length) {
    return `<div class="form-group">${label}
      <select class="form-select" id="${escAttr(id)}" data-setting="${escAttr(name)}">
        ${options.map(([v, text]) =>
          `<option value="${escAttr(v)}"${String(v) === String(value) ? ' selected' : ''}>${escHtml(text)}</option>`).join('')}
      </select></div>`;
  }
  if (t === 'choice') {
    return `<div class="form-group">${label}
      <select class="form-select" id="${escAttr(id)}" data-setting="${escAttr(name)}">
        ${(field.options || []).map(o => {
          const [v, text] = Array.isArray(o) ? o : [o, o];
          return `<option value="${escAttr(v)}"${String(v) === String(value) ? ' selected' : ''}>${escHtml(text)}</option>`;
        }).join('')}
      </select></div>`;
  }
  return `<div class="form-group">${label}
    <input type="text" class="form-input" id="${escAttr(id)}"
           data-setting="${escAttr(name)}" value="${escAttr(value ?? '')}"
           ${field.placeholder ? `placeholder="${escAttr(field.placeholder)}"` : ''}></div>`;
}

/* Each list-backed setting type has its own options endpoint, as [[value, text], …].
   Unreachable options come back empty rather than throwing: the field then
   falls back to the control above, which is still an honest way to set what
   this control stores. */
async function _settingsOptions(type) {
  const SOURCES = {
    saved_view: '/dashboards/api/options/saved_view/',
    project: '/dashboards/api/options/project/',
    report_card: '/dashboards/api/options/report_card/',
  };
  const url = SOURCES[type];
  if (!url) return [];
  try {
    return await apiJson(url);
  } catch (e) {
    return [];
  }
}

function _settingsBody(widget, spec, lists) {
  const schema = spec.settings || {};
  if (!Object.keys(schema).length) {
    // "Nothing to configure" is not "nothing to say": the widget's own
    // description still explains what its card shows.
    return `<p class="muted-note">${escHtml(spec.description || '')}</p>
      <p class="muted-note">This widget has nothing to configure.</p>`;
  }
  const current = widget.settings || {};
  return Object.entries(schema)
    .map(([name, field]) => _settingsField(name, field, current[name], lists[field.type] || []))
    .join('');
}

async function openWidgetSettings(widgetId) {
  const widget = (DASH.current.widgets || []).find(w => String(w.id) === String(widgetId));
  if (!widget) return;
  const spec = (DASH.catalog.widgets || {})[widget.kind] || {};
  const schema = spec.settings || {};

  const el = _ensureWidgetSettingsModal();
  // The widget's name and description change per call while the overlay is
  // reused, so they are written here with textContent — the way JackilModal's
  // own dialogs carry their words.
  el.querySelector('.modal-title').textContent = spec.label || widget.kind;
  const note = el.querySelector('[data-ws-description]');
  note.textContent = spec.description || '';
  note.hidden = !spec.description;

  const body = el.querySelector('#ws-body');
  if (Object.keys(schema).length) {
    body.innerHTML = '<span class="muted-note">Loading…</span>';
    // Each picker's options are fetched before the form is drawn, so a select
    // is never painted empty and filled a moment later. One request per
    // distinct type in the schema.
    const types = [...new Set(Object.values(schema).map(f => f.type))];
    const lists = {};
    await Promise.all(types.map(async (t) => { lists[t] = await _settingsOptions(t); }));
    body.innerHTML = _settingsBody(widget, spec, lists);
  } else {
    body.innerHTML = _settingsBody(widget, spec, {});
  }
  JackilModal.open('widget-settings');

  // Settings belong to the widget whose button was pressed, so the handler is
  // replaced on every open — a stale closure would write into the previous
  // widget's settings and repaint the wrong card.
  el.querySelector('#ws-save').onclick = () => {
    const next = {};
    for (const [name, field] of Object.entries(schema)) {
      const input = el.querySelector(`[data-setting="${CSS.escape(name)}"]`);
      if (!input) continue;
      if (field.type === 'bool') next[name] = input.checked;
      else if (field.type === 'int' || field.type === 'saved_view') {
        next[name] = parseInt(input.value, 10);
      } else next[name] = input.value;
    }
    widget.settings = next;
    DASH.dirty = true;
    JackilModal.close();
    // The title lives in the card's header and paintWidget repaints only
    // bodies, so without this a renamed tile keeps its old name on screen until
    // a reload — and giving a headless stat tile a title has to bring its
    // header back, which is what that class hides.
    const shell = document.querySelector(`[data-widget-body="${CSS.escape(String(widget.id))}"]`)
      ?.closest('.dash-widget');
    const custom = (next.title || '').trim();
    if (shell && custom) shell.classList.remove('dash-widget-headless');
    const heading = shell && shell.querySelector('.dash-widget-title');
    if (heading) heading.textContent = custom || spec.label || widget.kind;
    // Repaint just this widget, so the change is visible without a round trip.
    _repaintWidget(widget);
    showToast('Widget updated — saved when you leave edit mode', 'success');
  };
}

function _repaintWidget(widget) {
  const body = document.querySelector(`[data-widget-body="${CSS.escape(String(widget.id))}"]`);
  if (!body) return;
  paintWidget(body, widget);
}

/* Built once and reused, for the reason JackilModal gives in its own comment:
   an overlay already on the modal stack cannot have its node replaced from
   under it, which is what rebuilding per call would do when one widget's Save
   opens another widget's form. */
function _ensureWidgetSettingsModal() {
  const existing = document.getElementById('widget-settings');
  if (existing) return existing;
  document.body.insertAdjacentHTML('beforeend', `<div class="modal-overlay" id="widget-settings" aria-hidden="true">
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="ws-title">
      <div class="modal-header">
        <div class="modal-title" id="ws-title"></div>
        <button type="button" class="modal-close" id="ws-x" aria-label="Close">
          <svg viewBox="0 0 24 24"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>
      <div class="modal-body">
        <p class="muted-note ws-description" data-ws-description></p>
        <div id="ws-body"></div>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-outline" id="ws-cancel">Cancel</button>
        <button type="button" class="btn btn-mint" id="ws-save">Save</button>
      </div>
    </div>
  </div>`);
  const el = document.getElementById('widget-settings');
  const dismiss = () => JackilModal.close();
  el.querySelector('#ws-x').onclick = dismiss;
  el.querySelector('#ws-cancel').onclick = dismiss;
  return el;
}
