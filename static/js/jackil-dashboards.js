/* Widget dashboards — the grid on the Dashboard page.
 *
 * The layout lives server-side (/dashboards/api/), Gridstack owns the drag
 * and resize, and each widget paints from its contract-shaped data endpoint
 * (see jackil-widgets.js).
 *
 * Two modes. In *view* mode the grid is static and widgets refresh on a poll.
 * In *edit* mode Gridstack is unlocked, widgets grow their settings and remove
 * controls, an add-widget rail opens beside the grid, and the layout is saved
 * when you leave the mode — one PUT for the whole grid rather than one request
 * per nudge, because dragging a widget across a row emits dozens of change
 * events and every one of them is a layout nobody asked to keep.
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

/* The board list and the registry are fetched together, once. The catalog is
   kept on DASH across renders — a rail reopen or a save would otherwise ask
   for the same table again — but re-fetched after a reload, so new widget kinds
   deployed server-side arrive without any JavaScript changing. */
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

//: Below 720px the grid collapses to one column (see _dashFitColumns), so
//: editing is offered on wide screens only: #dash-actions — Edit layout, Add
//: widget and the per-widget buttons — renders nothing at all when the grid is
//: about to collapse. Arranging a one-column stack and saving it would
//: overwrite the real twelve-column layout with a phone-sized one.
const DASH_NARROW = 720;

function _dashToolbar() {
  const opts = DASH.boards.map(b =>
    `<option value="${escAttr(b.id)}"${b.id === DASH.current.id ? ' selected' : ''}>`
    + `${escHtml(b.name)}${b.is_mine ? '' : ` (${escHtml(b.owner)})`}</option>`).join('');
  const board = DASH.current;
  const editable = board.is_mine && window.innerWidth >= DASH_NARROW;
  const actions = !editable ? '' : `
    <button class="btn btn-${DASH.editing ? 'mint' : 'sky'} btn-sm" id="dash-edit">
      ${DASH.editing ? 'Done' : 'Edit layout'}</button>
    ${DASH.editing ? '<button class="btn btn-lav btn-sm" id="dash-add">+ Add widget</button>' : ''}
    <button class="btn btn-mint btn-sm" id="dash-new" title="New dashboard">+ New</button>
    <button class="btn btn-sky btn-sm" id="dash-rename">Rename</button>
    <button class="btn btn-${board.is_default ? 'lemon' : 'peach'} btn-sm" id="dash-default"
            ${board.is_default ? 'disabled title="This is already your landing dashboard"' : ''}>
      ${board.is_default ? 'Default' : 'Make default'}</button>
    <button class="btn btn-${board.shared ? 'lemon' : 'lav'} btn-sm" id="dash-share">
      ${board.shared ? 'Stop sharing' : 'Share'}</button>
    <button class="btn btn-rose btn-sm" id="dash-delete">Delete</button>`;
  return `
    <div class="dash-toolbar">
      <select class="form-select dash-switch" id="dash-switch" aria-label="Dashboard">${opts}</select>
      ${board.is_mine ? '' : `<span class="chip">shared by ${escHtml(board.owner)} · read-only</span>`}
      <span class="dash-toolbar-spacer"></span>
      <span id="dash-actions" class="dash-actions">${actions}</span>
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
  // The two per-widget controls are editing affordances: CSS hides them until
  // the root carries .dash-editing, and they are not built at all on a board
  // this user cannot change or a screen too narrow to arrange.
  const editable = DASH.editing && DASH.current.is_mine && window.innerWidth >= DASH_NARROW;
  return `
    <div class="dash-widget${headless ? ' dash-widget-headless' : ''}" data-kind="${escAttr(widget.kind)}">
      <div class="dash-widget-head">
        <span class="dash-widget-title">${escHtml(title)}</span>
        ${editable ? `<span class="dash-widget-actions">
          <button class="btn btn-lav btn-xs dash-w-settings" data-id="${escAttr(widget.id)}"
                  title="Widget settings">Settings</button>
          <button class="btn btn-rose btn-xs dash-w-remove" data-id="${escAttr(widget.id)}"
                  title="Remove widget">&times;</button>
        </span>` : ''}
      </div>
      <div class="dash-widget-body" data-widget-body="${escAttr(widget.id)}">
        <span class="muted-note">Loading…</span>
      </div>
    </div>`;
}

//: Below 720px the grid collapses to one column. Done after the widgets are
//: placed, not with Gridstack's columnOpts breakpoints: those apply before
//: any widget exists, and the one-column stack then came out in reverse.
//: 'list' keeps reading order (row, then column).
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

  // Leaving edit mode by any route — Done, switching boards, deleting — has to
  // take the rail with it. It hangs off <body>, so it outlives this repaint on
  // its own.
  if (!DASH.editing) closeWidgetCatalog();

  host.innerHTML = _dashToolbar()
    + '<div class="grid-stack" id="dash-grid"></div>';

  // Gridstack rewrites the container, so it is rebuilt rather than reused.
  // gridMake carries the shared base (cellHeight, margin, animate, float) and
  // the renderCB override the page needs.
  DASH.grid = gridMake(document.getElementById('dash-grid'), {
    column: DASH.catalog.grid_columns || 12,
    disableDrag: !DASH.editing || !DASH.current.is_mine,
    disableResize: !DASH.editing || !DASH.current.is_mine,
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

  DASH.grid.on('change', () => { DASH.dirty = true; });
  _dashFitColumns();
  _dashBindChrome(host);
  _dashPaintAll();
}

function _dashBindChrome(host) {
  host.classList.toggle('dash-editing', DASH.editing);

  const sw = document.getElementById('dash-switch');
  if (sw) sw.onchange = async () => {
    // A board switch while editing is the same "I'm finished arranging" that
    // Done means, so it saves first rather than dropping the layout.
    if (DASH.editing) await _dashSaveLayout();
    DASH.editing = false;
    DASH.current = DASH.boards.find(b => b.id === sw.value) || DASH.current;
    _dashRender();
  };

  const edit = document.getElementById('dash-edit');
  if (edit) edit.onclick = async () => {
    if (DASH.editing) {
      await _dashSaveLayout();
      DASH.editing = false;
    } else {
      DASH.editing = true;
    }
    _dashRender();
  };

  const add = document.getElementById('dash-add');
  if (add) add.onclick = () => openWidgetCatalog();

  const on = (id, fn) => {
    const el = document.getElementById(id);
    if (el) el.onclick = fn;
  };

  on('dash-new', async () => {
    const name = await JackilModal.prompt('Name the new dashboard', { placeholder: 'NOC wall' });
    if (!name) return;
    try {
      const board = await apiJson('/dashboards/api/', {
        method: 'POST', body: JSON.stringify({ name }) });
      DASH.boards.push(board);
      DASH.current = board;
      DASH.editing = false;
      _dashRender();
      showToast(`Created ${board.name}`, 'success');
    } catch (e) { showToast(e.message || 'Could not create it', 'error'); }
  });

  on('dash-rename', async () => {
    const name = await JackilModal.prompt('Rename this dashboard', { value: DASH.current.name });
    if (!name || name === DASH.current.name) return;
    await _dashPatch({ name }, `Renamed to ${name}`);
  });

  on('dash-default', () =>
    _dashPatch({ is_default: true }, 'This is now the dashboard you land on'));

  on('dash-share', async () => {
    const turningOn = !DASH.current.shared;
    if (turningOn && !(await JackilModal.confirm(
      'Share this dashboard with everyone on this Jackil? They will be able to '
      + 'see it but not change it.', { confirmText: 'Share' }))) return;
    try {
      DASH.current = await apiJson(`/dashboards/api/${DASH.current.id}/share/`, {
        method: 'POST', body: JSON.stringify({ shared: turningOn }) });
      _dashReplaceCurrent();
      _dashRender();
      showToast(turningOn ? 'Shared' : 'No longer shared', 'success');
    } catch (e) { showToast(e.message || 'Could not change sharing', 'error'); }
  });

  on('dash-delete', async () => {
    if (DASH.boards.filter(b => b.is_mine).length < 2) {
      showToast('This is your only dashboard — make another first', 'error');
      return;
    }
    if (!(await JackilModal.confirm(
      `Delete "${DASH.current.name}"? Its widgets and layout go with it.`,
      { confirmText: 'Delete', danger: true }))) return;
    const gone = DASH.current.id;
    try {
      await apiJson(`/dashboards/api/${gone}/`, { method: 'DELETE' });
    } catch (e) { showToast(e.message || 'Could not delete it', 'error'); return; }
    DASH.boards = DASH.boards.filter(b => b.id !== gone);
    DASH.current = DASH.boards.find(b => b.is_default && b.is_mine) || DASH.boards[0];
    DASH.editing = false;
    _dashRender();
    showToast('Dashboard deleted', 'success');
  });

  host.querySelectorAll('.dash-w-remove').forEach(btn => btn.onclick = () => {
    const el = btn.closest('.grid-stack-item');
    if (el) { DASH.grid.removeWidget(el); DASH.dirty = true; }
  });
  host.querySelectorAll('.dash-w-settings').forEach(btn => btn.onclick = () => {
    openWidgetSettings(btn.dataset.id);
  });
}

function _dashReplaceCurrent() {
  const i = DASH.boards.findIndex(b => b.id === DASH.current.id);
  if (i >= 0) DASH.boards[i] = DASH.current;
}

async function _dashPatch(body, okMessage) {
  try {
    DASH.current = await apiJson(`/dashboards/api/${DASH.current.id}/`, {
      method: 'PATCH', body: JSON.stringify(body) });
  } catch (e) {
    showToast(e.message || 'Could not save that', 'error');
    return;
  }
  // is_default is exclusive per owner, so the others in the list are stale.
  if ('is_default' in body) {
    DASH.boards.forEach(b => { if (b.is_mine) b.is_default = false; });
  }
  _dashReplaceCurrent();
  _dashRender();
  showToast(okMessage, 'success');
}

/* ── Persistence ───────────────────────────────────────────────────────── */

function _dashCollectLayout() {
  // Read geometry back off Gridstack rather than trusting our own copy: the
  // library reflows neighbours when one widget moves, and those neighbours
  // never fired an event of their own.
  //
  // Off the live nodes, not off save(). Gridstack's save() runs every node
  // through removeInternalForSave (gridstack-all.js, v12.4.0), which ends
  //   1!==e.w && e.w!==e.minW || delete e.w
  // — it deletes w when the width is 1 OR equal to the node's minW, and h on
  // the same rule. _dashRender passes the catalogue's minW/minH into every
  // addWidget, so every widget sitting at its minimum comes back from save()
  // carrying no size at all. Filling that hole from DASH.current.widgets —
  // the geometry the *server* last sent — meant a resize down to the minimum
  // was thrown away and replaced by the size the widget had before it, and
  // with float:true the restored, larger widget then collided on the next
  // load and shoved its neighbours down. One discarded resize scrambled the
  // board. el.gridstackNode is the node Gridstack is actually laying out, and
  // its x/y/w/h are always complete.
  const byId = new Map(DASH.current.widgets.map(w => [String(w.id), w]));
  return DASH.grid.getGridItems().map((el) => {
    // An item Gridstack has already detached carries no node. Skipping it
    // beats throwing: the alternative is one stray element failing the whole
    // save, which is the scrambled-layout-without-a-message case again.
    const node = el.gridstackNode;
    if (!node) return {};
    const original = byId.get(String(node.id)) || {};
    return {
      // The widget's own id, so a save moves widgets instead of destroying and
      // recreating them. Without it layout_update deleted every row and minted
      // fresh UUIDs, so anything keyed by widget id was invalidated on every
      // save — and _dashCollectLayout recovers kind and settings by looking up
      // exactly that id, so a miss dropped the widget from the payload
      // entirely: a save that deleted a widget rather than moving it.
      id: original.id,
      // Gridstack knows nothing about either, so they keep coming from our
      // own copy of the widget.
      kind: original.kind,
      settings: original.settings || {},
      x: node.x, y: node.y, w: node.w, h: node.h,
    };
  }).filter(w => w.kind);
}

async function _dashSaveLayout() {
  if (!DASH.dirty || !DASH.current.is_mine) return;
  // The narrow grid is one column wide (see _dashFitColumns). Its geometry is
  // a phone's, not the board's: saving it would overwrite the real layout with
  // twelve widgets stacked at x=0, and there is nothing to arrange on such a
  // screen in the first place. The dirty flag survives — rotating back to
  // landscape saves what was actually arranged.
  if (DASH.grid.getColumn() !== (DASH.catalog.grid_columns || 12)) return;
  const widgets = _dashCollectLayout();
  try {
    DASH.current = await apiJson(
      `/dashboards/api/${DASH.current.id}/layout/`,
      { method: 'PUT', body: JSON.stringify({ widgets }) });
    const i = DASH.boards.findIndex(b => b.id === DASH.current.id);
    if (i >= 0) DASH.boards[i] = DASH.current;
    DASH.dirty = false;
    showToast('Layout saved', 'success');
  } catch (e) {
    showToast(e.message || 'Could not save the layout', 'error');
  }
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

  // Refresh widget contents on a poll — but never while the layout is being
  // edited. Repainting under a drag is how a widget ends up somewhere nobody
  // dropped it, and the new SVGs restart their draw animations mid-nudge. No
  // pollingInterval helper in Jackil, so the interval is owned here — and
  // cleared first, so re-entering the page does not stack another one.
  if (DASH.pollTimer) clearInterval(DASH.pollTimer);
  DASH.pollTimer = setInterval(() => {
    if (DASH.editing) return;
    if (document.visibilityState === 'visible' && document.getElementById('dash-root')) {
      _dashPaintAll();
    }
  }, 30000);
}

document.addEventListener('DOMContentLoaded', () => {
  if (document.getElementById('dash-root')) loadDashboards();
});

/* ── Add-widget rail ───────────────────────────────────────────────────── */

//: Group → accent. The rail's groups are the registry's own (see widgets.py):
//: tickets and SLA in the two "workload" colours, my-work in the information
//: lavender, people in mint. An unknown group falls into the last bucket so a
//: widget added to the registry on the server still appears in the rail rather
//: than vanishing from it.
const GROUP_ACCENT = { tickets: 'sky', sla: 'peach', work: 'lav', people: 'mint', projects: 'coral', vigil: 'sky' };
const GROUP_LABEL = { tickets: 'Tickets', sla: 'SLA', work: 'My work', people: 'People', projects: 'Projects', vigil: 'Vigil' };
const GROUP_ORDER = ['tickets', 'sla', 'work', 'people', 'projects', 'vigil'];

function _railHtml() {
  const widgets = DASH.catalog.widgets || {};
  const byGroup = new Map(GROUP_ORDER.map(g => [g, []]));
  for (const [kind, spec] of Object.entries(widgets)) {
    const bucket = byGroup.get(spec.group) || byGroup.get(GROUP_ORDER[GROUP_ORDER.length - 1]);
    if (!bucket) continue;
    bucket.push([kind, spec]);
  }
  const sections = GROUP_ORDER.map((group) => {
    const items = (byGroup.get(group) || []).sort((a, b) =>
      a[1].label.localeCompare(b[1].label));
    if (!items.length) return '';
    return `
      <div class="rail-group rail-${escAttr(group)}">
        <div class="rail-group-label">${escHtml(GROUP_LABEL[group] || group)}</div>
        ${items.map(([kind, spec]) => `
          <div class="rail-card" data-add-kind="${escAttr(kind)}"
               title="${escAttr(spec.description || '')}">
            <div class="rail-card-name">${escHtml(spec.label)}</div>
            <div class="rail-card-desc">${escHtml(spec.description || '')}</div>
            <button class="rail-add btn-${escAttr(GROUP_ACCENT[group] || 'sky')}"
                    data-add-kind="${escAttr(kind)}"
                    aria-label="Add ${escAttr(spec.label)}">+</button>
          </div>`).join('')}
      </div>`;
  }).join('');
  return `<aside class="dash-rail" id="dash-rail">
    <div class="rail-head">
      <span>Add a widget</span>
      <button class="modal-close" id="rail-close" aria-label="Close">
        <svg viewBox="0 0 24 24"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
    </div>
    <div class="rail-body">${sections}</div>
  </aside>`;
}

function _addWidgetOfKind(kind) {
  const spec = (DASH.catalog.widgets || {})[kind];
  if (!spec) return;
  // No x/y: Gridstack finds the first free slot, which is what "add" means
  // when the operator has not chosen a position. The id is local for the same
  // reason — the server mints the real one when the layout is saved.
  const id = `new-${kind}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const widget = {
    id, kind,
    w: spec.w, h: spec.h,
    settings: Object.fromEntries(
      Object.entries(spec.settings || {}).map(([k, f]) => [k, f.default])),
  };
  DASH.current.widgets.push(widget);
  DASH.grid.addWidget({
    w: spec.w, h: spec.h, minW: spec.min_w, minH: spec.min_h,
    id, content: _widgetShell(widget),
  });
  DASH.dirty = true;
  // The new card's two buttons exist only in the shell just added, so the
  // chrome has to be bound again for this one widget.
  _dashBindChrome(document.getElementById('dash-root'));
  _dashPaintAll();
  showToast(`${spec.label} added`, 'success');
}

//: The rail is fixed-position, so it has to hang off <body>. #dash-root
//: carries .fade-in, whose `both` fill mode leaves transform: translateY(0)
//: on the element permanently — and a transformed ancestor becomes the
//: containing block for its fixed children. Mounted inside #dash-root the rail
//: sized itself to the dashboard's box instead of the viewport, so on a
//: near-empty layout it collapsed to the header plus a sliver of cards.
//: Leaving edit mode closes it (see _dashRender); removing it is what this
//: pagehide hook adds, because nothing else takes a body-mounted element with
//: it when the operator navigates away mid-edit — and a stale rail would be
//: re-opened by openWidgetCatalog() as the *previous* board's widget list.
function closeWidgetCatalog(remove) {
  const el = document.getElementById('dash-rail');
  if (!el) return;
  el.classList.remove('open');
  if (remove) el.remove();
}

function openWidgetCatalog() {
  const rail = document.getElementById('dash-rail');
  if (rail) { rail.classList.toggle('open'); return; }
  if (!document.getElementById('dash-root')) return;
  document.body.insertAdjacentHTML('beforeend', _railHtml());
  const el = document.getElementById('dash-rail');
  requestAnimationFrame(() => el.classList.add('open'));
  el.querySelector('#rail-close').onclick = () => closeWidgetCatalog();
  el.querySelectorAll('[data-add-kind]').forEach((node) => {
    node.addEventListener('click', (ev) => {
      ev.stopPropagation();
      _addWidgetOfKind(node.dataset.addKind);
    });
  });
}

//: Body-mounted, so the rail does not disappear with the page that owns it —
//: leaving edit mode is what closes it (see _dashRender), and this catches
//: navigating away while still in it.
window.addEventListener('pagehide', () => closeWidgetCatalog(true));
