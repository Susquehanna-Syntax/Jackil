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
    .map((c) => `<th>${escHtml(c)}</th>`).join('')}</tr></thead>`;
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
      <svg viewBox="0 0 78 78" class="dash-gauge-ring" aria-hidden="true">
        <circle cx="39" cy="39" r="${r}" class="gauge-bg"/>
        <circle cx="39" cy="39" r="${r}" stroke="var(--${pastel}-ink)"
                stroke-dasharray="${circumference.toFixed(1)}"
                stroke-dashoffset="${offset.toFixed(1)}" class="gauge-fill"/>
      </svg>
      <div class="dash-gauge-text">${escHtml(text)}</div>
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
  const max = Math.max(...values, 0) || 1;
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
  if (data.kind === 'bar') {
    const groupW = plotW / Math.max(1, labels.length);
    const barW = Math.max(1, (groupW * 0.72) / Math.max(1, series.length));
    xOf = (i) => padL + groupW * i + groupW / 2;
    labels.forEach((label, li) => {
      const x0 = padL + groupW * li + (groupW - barW * series.length) / 2;
      series.forEach((s, si) => {
        const v = (s.values || [])[li] || 0;
        const top = y(v);
        // One series: each bar is its own category, so it takes its own slot.
        const fill = series.length > 1 ? colour(si) : colour(li);
        parts.push(`<rect x="${(x0 + si * barW).toFixed(1)}" y="${top.toFixed(1)}" width="${barW.toFixed(1)}" `
          + `height="${(padT + plotH - top).toFixed(1)}" rx="3" fill="${fill}">`
          + `<title>${escHtml(`${label}: ${v}`)}</title></rect>`);
      });
    });
  } else {
    const step = labels.length > 1 ? plotW / (labels.length - 1) : 0;
    xOf = (i) => padL + step * i;
    series.forEach((s, si) => {
      const vs = s.values || [];
      if (vs.length > 1) {
        parts.push(`<polyline fill="none" stroke="${colour(si)}" stroke-width="2" stroke-linejoin="round" `
          + `points="${vs.map((v, i) => `${xOf(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')}"/>`);
      }
      vs.forEach((v, i) => parts.push(`<circle cx="${xOf(i).toFixed(1)}" cy="${y(v).toFixed(1)}" r="2.5" fill="${colour(si)}">`
        + `<title>${escHtml(`${labels[i] ?? ''}: ${v}`)}</title></circle>`));
    });
  }

  // As many x labels as fit, evenly spaced, first and last always shown.
  const fit = Math.max(2, Math.floor(plotW / 56));
  const every = Math.max(1, Math.ceil(labels.length / fit));
  labels.forEach((label, i) => {
    if (i % every !== 0 && i !== labels.length - 1) return;
    const anchor = data.kind === 'bar' ? 'middle' : (i === 0 ? 'start' : (i === labels.length - 1 ? 'end' : 'middle'));
    parts.push(`<text class="axis-text" x="${xOf(i).toFixed(1)}" y="${H - 4}" text-anchor="${anchor}">${escHtml(label)}</text>`);
  });

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
  }
}
