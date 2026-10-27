/* Widget dashboards — the grid on the Dashboard page.
 *
 * The layout lives server-side (/dashboards/api/), Gridstack owns the drag
 * and resize, and each widget paints from its contract-shaped data endpoint
 * (see jackil-widgets.js).
 *
 * This phase is view mode only: the grid is static and widgets refresh on a
 * poll. Edit mode unlocks the grid, grows the per-widget controls, and fills
 * #dash-actions in the toolbar.
 */

const DASH = {
  boards: [],        // every dashboard visible to this user
  current: null,     // the one on screen
  catalog: null,     // widget registry from the server
  grid: null,        // the Gridstack instance
  editing: false,
  dirty: false,
  pollTimer: null,
};

/* ── Data ──────────────────────────────────────────────────────────────── */

async function _dashLoadAll() {
  const [boards, catalog] = await Promise.all([
    apiJson('/dashboards/api/'),
    DASH.catalog ? Promise.resolve(DASH.catalog)
                 : apiJson('/dashboards/api/catalog/'),
  ]);
  DASH.boards = boards;
  DASH.catalog = catalog;
  // Land on the default, or whatever is first — the server guarantees at
  // least one, so there is no empty state to design around.
  const wanted = DASH.current && boards.find(b => b.id === DASH.current.id);
  DASH.current = wanted || boards.find(b => b.is_default && b.is_mine) || boards[0];
}

/* ── Chrome ────────────────────────────────────────────────────────────── */

function _dashToolbar() {
  const opts = DASH.boards.map(b =>
    `<option value="${escAttr(b.id)}"${b.id === DASH.current.id ? ' selected' : ''}>`
    + `${escHtml(b.name)}${b.is_mine ? '' : ` (${escHtml(b.owner)})`}</option>`).join('');
  const board = DASH.current;
  return `
    <div class="dash-toolbar">
      <select class="form-select dash-switch" id="dash-switch" aria-label="Dashboard">${opts}</select>
      ${board.is_mine ? '' : `<span class="chip">shared by ${escHtml(board.owner)} · read-only</span>`}
      <span class="dash-toolbar-spacer"></span>
      <span id="dash-actions"></span>
    </div>`;
}

// Returns what goes *inside* Gridstack's own .grid-stack-item-content. Emitting
// a second element with that class nests one inside the other, and only the
// outer one is stretched to the cell — so every widget collapses to the height
// of its content and leaves dead space below it.
function _widgetShell(widget) {
  const spec = (DASH.catalog.widgets || {})[widget.kind] || {};
  // An operator-set title wins over the widget's own name: a dashboard may
  // hold three series charts, and "Series chart" three times names none of
  // them.
  const custom = ((widget.settings || {}).title || '').trim();
  const title = custom || spec.label || widget.kind;
  // A stat tile names its own number ("Open", "Overdue"), so its card needs
  // no "Stat tile" header unless someone gave it a title.
  const headless = spec.shape === 'stat' && !custom;
  return `
    <div class="dash-widget${headless ? ' dash-widget-headless' : ''}" data-kind="${escAttr(widget.kind)}">
      <div class="dash-widget-head">
        <span class="dash-widget-title">${escHtml(title)}</span>
      </div>
      <div class="dash-widget-body" data-widget-body="${escAttr(widget.id)}">
        <span class="muted-note">Loading…</span>
      </div>
    </div>`;
}

//: Below 720px the grid collapses to one column. Done after the widgets are
//: placed, not with Gridstack's columnOpts breakpoints: those apply before
//: any widget exists, and the one-column stack then came out in reverse.
//: 'list' keeps reading order (row, then column). Editing is only offered on
//: wider screens, so a phone never saves a one-column layout.
const DASH_NARROW = 720;
function _dashFitColumns() {
  if (!DASH.grid) return;
  const want = window.innerWidth < DASH_NARROW ? 1 : (DASH.catalog.grid_columns || 12);
  if (DASH.grid.getColumn() !== want) DASH.grid.column(want, 'list');
}
window.addEventListener('resize', () => {
  clearTimeout(DASH._fitTimer);
  DASH._fitTimer = setTimeout(_dashFitColumns, 150);
});

/* ── Shared grid ───────────────────────────────────────────────────────── */

// The grid's base: 90px rows and 8px gaps. float:true lets widgets sit at the
// row they were arranged on rather than being pulled to the top of the column.
function gridBaseOptions() {
  return { cellHeight: 90, margin: 8, animate: true, float: true };
}

// Gridstack's default renderCB assigns widget content with textContent, so a
// markup string arrives on screen as literal angle brackets. Ours is built
// with every interpolated value already through escHtml/escAttr (see
// _widgetShell), so innerHTML is the correct assignment.
function gridMake(el, options) {
  GridStack.renderCB = (node, w) => { node.innerHTML = w.content || ''; };
  return GridStack.init({ ...gridBaseOptions(), ...options }, el);
}

/* ── Render ────────────────────────────────────────────────────────────── */

function _dashRender() {
  const host = document.getElementById('dash-root');
  if (!host) return;

  host.innerHTML = _dashToolbar()
    + '<div class="grid-stack" id="dash-grid"></div>';

  // Gridstack rewrites the container, so it is rebuilt rather than reused.
  // gridMake carries the shared base (cellHeight, margin, animate, float) and
  // the renderCB override the page needs.
  DASH.grid = gridMake(document.getElementById('dash-grid'), {
    column: DASH.catalog.grid_columns || 12,
    disableDrag: true,
    disableResize: true,
  });

  for (const w of DASH.current.widgets) {
    DASH.grid.addWidget({
      x: w.x, y: w.y, w: w.w, h: w.h,
      minW: (DASH.catalog.widgets[w.kind] || {}).min_w || 1,
      minH: (DASH.catalog.widgets[w.kind] || {}).min_h || 1,
      id: w.id,
      content: _widgetShell(w),
    });
  }

  _dashFitColumns();
  _dashBindChrome(host);
  _dashPaintAll();
}

function _dashBindChrome(host) {
  const sw = document.getElementById('dash-switch');
  if (sw) sw.onchange = () => {
    DASH.current = DASH.boards.find(b => b.id === sw.value) || DASH.current;
    _dashRender();
  };
}

/* ── Widget bodies ─────────────────────────────────────────────────────── */

function _dashPaintAll() {
  for (const w of DASH.current.widgets) {
    const body = document.querySelector(`[data-widget-body="${CSS.escape(String(w.id))}"]`);
    if (!body) continue;
    Promise.resolve()
      .then(() => paintWidget(body, w))
      .catch((e) => {
        body.innerHTML = `<div class="dash-failed"><span class="muted-note">Couldn't load `
          + `this widget: ${escHtml(e.message || 'Failed to load')}</span></div>`;
      });
  }
}

/* ── Entry ─────────────────────────────────────────────────────────────── */

async function loadDashboards() {
  const host = document.getElementById('dash-root');
  if (!host) return;
  try {
    await _dashLoadAll();
  } catch (e) {
    host.innerHTML = `<div class="empty-state"><div class="empty-state-title">`
      + `Couldn't load your dashboard</div><p>${escHtml(e.message)}</p></div>`;
    return;
  }
  _dashRender();

  // Refresh widget contents on a poll. No pollingInterval helper in Jackil,
  // so the interval is owned here — and cleared first, so re-entering the
  // page does not stack another one.
  if (DASH.pollTimer) clearInterval(DASH.pollTimer);
  DASH.pollTimer = setInterval(() => {
    if (document.visibilityState === 'visible' && document.getElementById('dash-root')) {
      _dashPaintAll();
    }
  }, 30000);
}

document.addEventListener('DOMContentLoaded', () => {
  if (document.getElementById('dash-root')) loadDashboards();
});
