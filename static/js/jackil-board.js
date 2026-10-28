/* The board screen (M5 p04b). One JSON document holds every column and card.
   Every action posts to its endpoint and re-reads the document — no optimistic
   local mutation, so the rank and WIP count the server computed are what
   appears on screen. A 409 means a Kanban column is at its WIP limit; the
   dialog asks before forcing the move through. */
const BD = {
  root: null,
  data: null,
  dragging: null,
  moving: null,
  people: new Map(),
  scrum: false,
};

const BD_TYPE_TONE = { epic: 'tc-lav', story: 'tc-sky', task: 'tc-mint', bug: 'tc-rose' };
const BD_PRIORITY_TONE = { critical: 'tc-rose', high: 'tc-peach' };

function bdUrl(name) {
  return BD.root.getAttribute(name);
}

function bdQuery() {
  const params = new URLSearchParams();
  const assignee = document.getElementById('bd-assignee').value;
  const type = document.getElementById('bd-type').value;
  const q = document.getElementById('bd-q').value.trim();
  if (assignee) params.set('assignee', assignee);
  if (type) params.set('type', type);
  if (q) params.set('q', q);
  return params.toString();
}

async function bdLoad() {
  const query = bdQuery();
  try {
    BD.data = await apiJson(`${bdUrl('data-data-url')}?${query}`);
    bdRender(BD.data);
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function bdMove(issueId, columnId, before) {
  const moved = await bdPost(issueId, columnId, before, false);
  if (moved.ok) {
    bdCongratulate(issueId, moved.body);
    return;
  }
  const err = moved.body;
  if (err.status === 409) {
    const go = await JackilModal.confirm(`${err.message} Move it anyway?`, {
      confirmText: 'Move anyway',
    });
    if (!go) return;
    const forced = await bdPost(issueId, columnId, before, true);
    if (forced.ok) bdCongratulate(issueId, forced.body);
    else showToast(forced.body.message, 'error');
    return;
  }
  showToast(err.message, 'error');
}

/* The move re-reads the document first, so the card's key is looked up in the
   payload that was current just before it moved. */
function bdCongratulate(issueId, body) {
  if (body.category !== 'done' || !BD.scrum) return;
  const card = bdFindCard(issueId);
  if (card) showToast(`${card.key} is done`, 'success');
}

/* A failed fetch comes back as the thrown Error; a successful one as the
   body. The caller tells them apart by `ok` because the WIP limit answer has
   to arrive here rather than as a toast from the post itself. */
async function bdPost(issueId, columnId, before, force) {
  try {
    const body = await apiJson(bdUrl('data-move-url'), {
      method: 'POST',
      body: JSON.stringify({
        issue: issueId,
        column: columnId,
        before: before ?? null,
        ...(force ? { force: true } : {}),
      }),
    });
    await bdLoad();
    return { ok: true, body };
  } catch (err) {
    return { ok: false, body: err };
  }
}

function bdFindCard(issueId) {
  if (!BD.data) return null;
  for (const column of BD.data.columns) {
    const card = column.issues.find((issue) => String(issue.id) === String(issueId));
    if (card) return card;
  }
  return null;
}

function bdCardHtml(card) {
  const priority = BD_PRIORITY_TONE[card.priority]
    ? `<span class="pill ${BD_PRIORITY_TONE[card.priority]}">${escHtml(bdLabel(card.priority))}</span>`
    : '';
  const subs = card.subtasks_total
    ? `<span class="bd-subs">${card.subtasks_done}/${card.subtasks_total} sub-tasks</span>`
    : '';
  const avatar = card.assignee
    ? `<span class="bd-avatar" style="background: var(--${escAttr(card.assignee.color)})" title="${escAttr(card.assignee.name)}">${escHtml(card.assignee.initials)}</span>`
    : '';
  return (
    `<li class="bd-card" draggable="true" data-issue-id="${escAttr(card.id)}">` +
    '<div class="bd-card-top">' +
    `<a class="issue-key" href="${escAttr(card.url)}">${escHtml(card.key)}</a>` +
    `<span class="pill ${BD_TYPE_TONE[card.type] || 'tc-sky'}">${escHtml(bdLabel(card.type))}</span>` +
    priority +
    '</div>' +
    `<a class="bd-title" href="${escAttr(card.url)}">${escHtml(card.title)}</a>` +
    '<div class="bd-card-foot">' +
    `<span class="bd-pts">${card.points ?? '&ndash;'}</span>` +
    subs +
    avatar +
    `<button type="button" class="btn btn-ghost btn-sm" data-bd-move="${escAttr(card.id)}">Move</button>` +
    '</div>' +
    '</li>'
  );
}

function bdCountHtml(column) {
  const words = column.wip_limit ? `${column.count} / ${column.wip_limit}` : `${column.count}`;
  let tone = '';
  if (column.wip_limit && column.count > column.wip_limit) tone = ' tc-rose';
  else if (column.wip_limit && column.count === column.wip_limit) tone = ' tc-lemon';
  return `<span class="pill${tone}">${words}</span>`;
}

function bdColumnHtml(column) {
  const cards = column.issues.length
    ? column.issues.map(bdCardHtml).join('')
    : '<li class="bd-empty">No cards</li>';
  return (
    `<section class="bd-col" data-column="${escAttr(column.id)}">` +
    `<div class="bd-col-head"><span class="bd-col-name">${escHtml(column.name)}</span>${bdCountHtml(column)}</div>` +
    `<ul class="bd-list" data-column="${escAttr(column.id)}">${cards}</ul>` +
    '</section>'
  );
}

//: "subtask" and "high" are API values; the pills say them the way the
//: project page does.
function bdLabel(value) {
  if (value === 'subtask') return 'Sub-task';
  const text = String(value || '');
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function bdSprintLine(data) {
  const line = document.getElementById('bd-sprint');
  if (!line) return;
  if (!BD.scrum) {
    line.textContent = '';
    return;
  }
  line.innerHTML = data.sprint
    ? `&middot; <span class="issue-key">${escHtml(data.sprint.name)}</span> &middot; ends ${escHtml(data.sprint.end_date)}`
    : 'No active sprint. Start one from the backlog.';
}

function bdRender(data) {
  bdSprintLine(data);
  BD.root.innerHTML = data.columns.map(bdColumnHtml).join('');
  bdMergePeople(data);
}

function bdMergePeople(data) {
  for (const column of data.columns) {
    for (const card of column.issues) {
      if (card.assignee) BD.people.set(String(card.assignee.id), card.assignee.name);
    }
  }
  const select = document.getElementById('bd-assignee');
  const current = select.value;
  // The chosen person may be filtered out of the payload entirely; keep that
  // option so the select's value survives the re-render.
  let options = '<option value="">Anyone</option><option value="me">Assigned to me</option>';
  if (current && current !== 'me' && !BD.people.has(current)) {
    const kept = select.querySelector(`option[value="${CSS.escape(current)}"]`);
    if (kept) options += `<option value="${escAttr(current)}">${escHtml(kept.textContent)}</option>`;
  }
  options += [...BD.people.entries()]
    .map(([id, name]) => `<option value="${escAttr(id)}">${escHtml(name)}</option>`)
    .join('');
  select.innerHTML = options;
  select.value = current;
}

function bdOpenMove(issueId) {
  BD.moving = issueId;
  const select = document.getElementById('bd-move-column');
  select.innerHTML = BD.data.columns
    .map((column) => `<option value="${escAttr(column.id)}">${escHtml(column.name)}</option>`)
    .join('');
  document.getElementById('bd-move-pos').value = 'top';
  JackilModal.open('bd-move-modal');
}

async function bdMoveOk() {
  const column = document.getElementById('bd-move-column').value;
  const list = BD.root.querySelector(`.bd-list[data-column="${CSS.escape(column)}"]`);
  const first = list ? list.querySelector('.bd-card') : null;
  const before =
    document.getElementById('bd-move-pos').value === 'top' && first
      ? first.getAttribute('data-issue-id')
      : null;
  await bdMove(BD.moving, column, before);
  JackilModal.close();
}

function bdBind() {
  ['bd-assignee', 'bd-type'].forEach((id) => {
    document.getElementById(id).addEventListener('change', bdLoad);
  });
  let timer = null;
  document.getElementById('bd-q').addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(bdLoad, 300);
  });
  document.getElementById('bd-move-ok').addEventListener('click', bdMoveOk);

  BD.root.addEventListener('dragstart', (e) => {
    const card = e.target.closest('.bd-card');
    if (!card) return;
    BD.dragging = card.getAttribute('data-issue-id');
    e.dataTransfer.setData('text/plain', BD.dragging);
  });

  BD.root.addEventListener('dragover', (e) => {
    const list = e.target.closest('.bd-list');
    if (!list) return;
    e.preventDefault();
    list.classList.add('bd-over');
  });

  BD.root.addEventListener('dragleave', (e) => {
    const list = e.target.closest('.bd-list');
    if (list) list.classList.remove('bd-over');
  });

  BD.root.addEventListener('drop', async (e) => {
    const list = e.target.closest('.bd-list');
    if (!list || !BD.dragging) return;
    e.preventDefault();
    list.classList.remove('bd-over');
    const target = e.target.closest('.bd-card');
    if (target && target.getAttribute('data-issue-id') === BD.dragging) return;
    const before = target ? target.getAttribute('data-issue-id') : null;
    await bdMove(BD.dragging, list.getAttribute('data-column'), before);
    BD.dragging = null;
  });

  BD.root.addEventListener('click', (e) => {
    const move = e.target.closest('[data-bd-move]');
    if (move) bdOpenMove(move.getAttribute('data-bd-move'));
  });
}

document.addEventListener('DOMContentLoaded', () => {
  BD.root = document.getElementById('bd-columns');
  if (!BD.root) return;
  BD.scrum = BD.root.getAttribute('data-scrum') === '1';
  bdBind();
  bdLoad();
});
