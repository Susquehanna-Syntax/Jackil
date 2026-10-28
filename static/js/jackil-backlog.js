/* Scrum planning screen (M5 p03b). The page is one JSON document: sprints,
   the backlog and load per person. Every action posts to its endpoint and
   re-reads the document — no optimistic local mutation, so the rank the
   server computed is always what appears on screen. */
const BL = {
  root: null,
  data: null,
  dragging: null,
  moving: null,
  starting: null,
  editing: null,
};

async function blLoad() {
  try {
    BL.data = await apiJson(BL.root.getAttribute('data-data-url'));
    blRender(BL.data);
  } catch (err) {
    showToast(err.message, 'error');
  }
}

function blUrl(name) {
  return BL.root.getAttribute(name);
}

function blDate(day) {
  const d = new Date();
  d.setDate(d.getDate() + day);
  return d.toISOString().slice(0, 10);
}

function blRowHtml(row) {
  const subtask = row.type === 'subtask';
  const move = subtask
    ? ''
    : `<button type="button" class="btn btn-ghost btn-sm" data-bl-move="${escAttr(row.id)}">Move</button>`;
  return (
    `<li class="bl-row"${subtask ? '' : ' draggable="true"'} data-issue-id="${escAttr(row.id)}">` +
    `<a class="issue-key" href="${escAttr(row.url)}">${escHtml(row.key)}</a>` +
    `<span class="bl-title">${escHtml(row.title)}</span>` +
    `<span class="bl-who">${escHtml(row.assignee_name || '')}</span>` +
    `<span class="bl-pts">${row.points ?? '&ndash;'}</span>` +
    move +
    '</li>'
  );
}

function blListHtml(id, issues) {
  const rows = issues.length
    ? issues.map(blRowHtml).join('')
    : '<li class="bl-empty">Drag issues here</li>';
  return `<ul class="bl-list" data-sprint="${escAttr(id)}">${rows}</ul>`;
}

function blSprintHtml(sprint, hasActive) {
  const dates =
    sprint.start_date && sprint.end_date
      ? `${escHtml(sprint.start_date)} &ndash; ${escHtml(sprint.end_date)}`
      : 'Not started';
  let buttons = '';
  if (sprint.state === 'active') {
    buttons += `<button type="button" class="btn btn-outline btn-sm" data-bl-complete="${escAttr(sprint.id)}">Complete</button>`;
  } else if (!hasActive) {
    buttons += `<button type="button" class="btn btn-mint btn-sm" data-bl-start="${escAttr(sprint.id)}">Start</button>`;
  }
  buttons += `<button type="button" class="btn btn-ghost btn-sm" data-bl-edit="${escAttr(sprint.id)}">Edit</button>`;
  const goal = sprint.goal ? `<div class="bl-goal">${escHtml(sprint.goal)}</div>` : '';
  return (
    `<section class="form-card bl-sprint">` +
    '<div class="bl-head">' +
    '<div>' +
    `<div class="bl-name">${escHtml(sprint.name)}</div>` +
    `<div class="bl-dates">${dates}</div>` +
    goal +
    '</div>' +
    `<div class="bl-actions"><span class="muted-note">${sprint.points} points</span>${buttons}</div>` +
    '</div>' +
    blListHtml(sprint.id, sprint.issues) +
    '</section>'
  );
}

function blRender(data) {
  const hasActive = data.sprints.some((sprint) => sprint.state === 'active');
  const sections = data.sprints.map((sprint) => blSprintHtml(sprint, hasActive));
  sections.push(
    '<section class="form-card bl-sprint"><div class="bl-head"><div>' +
    '<div class="bl-name">Backlog</div>' +
    '</div></div>' +
    blListHtml('', data.backlog) +
    '</section>',
  );
  BL.root.innerHTML = sections.join('');
  blRenderLoad(data.people);
}

function blClearLoadRows() {
  const card = document.getElementById('bl-load');
  if (!card) return;
  card.querySelectorAll('.bl-person, .muted-note').forEach((el) => el.remove());
}

function blRenderLoad(people) {
  const card = document.getElementById('bl-load');
  if (!card) return;
  blClearLoadRows();
  const rows = people
    .map((person) => {
      const known = Math.max(person.committed, person.velocity || 0, 1);
      const pct = Math.round((person.committed / known) * 100);
      let words;
      if (person.velocity === null) {
        words = `${person.committed} points &middot; No history yet`;
      } else if (person.committed > person.velocity) {
        words = `${person.committed} of usual ${person.velocity} points &mdash; over`;
      } else {
        words = `${person.committed} of usual ${person.velocity} points`;
      }
      const tone = person.velocity !== null && person.committed > person.velocity ? 'tc-rose' : 'tc-mint';
      return (
        `<div class="bl-person ${tone}">` +
        `<div class="bl-person-name">${escHtml(person.name)}</div>` +
        `<div class="bl-bar"><span style="width:${pct}%"></span></div>` +
        `<div class="bl-words">${words}</div>` +
        '</div>'
      );
    })
    .join('');
  card.insertAdjacentHTML(
    'beforeend',
    people.length ? rows : '<div class="muted-note">Nobody here yet.</div>',
  );
}

function blFindSprint(id) {
  return BL.data.sprints.find((sprint) => String(sprint.id) === String(id));
}

function blFail(err) {
  showToast(err.message, 'error');
}

function blBind() {
  document.getElementById('bl-create').addEventListener('click', () => blOpenSprint(null));
  document.getElementById('bl-move-ok').addEventListener('click', blMoveOk);
  document.getElementById('bl-start-ok').addEventListener('click', blStartOk);
  document.getElementById('bl-sprint-ok').addEventListener('click', blSprintOk);

  BL.root.addEventListener('dragstart', (e) => {
    const row = e.target.closest('.bl-row');
    if (!row) return;
    BL.dragging = row.getAttribute('data-issue-id');
    e.dataTransfer.setData('text/plain', BL.dragging);
  });

  BL.root.addEventListener('dragover', (e) => {
    const list = e.target.closest('.bl-list');
    if (!list) return;
    e.preventDefault();
    list.classList.add('bl-over');
  });

  BL.root.addEventListener('dragleave', (e) => {
    const list = e.target.closest('.bl-list');
    if (list) list.classList.remove('bl-over');
  });

  BL.root.addEventListener('drop', async (e) => {
    const list = e.target.closest('.bl-list');
    if (!list || !BL.dragging) return;
    e.preventDefault();
    list.classList.remove('bl-over');
    const target = e.target.closest('.bl-row');
    if (target && target.getAttribute('data-issue-id') === BL.dragging) return;
    const before = target ? target.getAttribute('data-issue-id') : null;
    const sprint = list.getAttribute('data-sprint') || null;
    try {
      await apiJson(blUrl('data-rank-url'), {
        method: 'POST',
        body: JSON.stringify({ issue: BL.dragging, before, sprint }),
      });
      BL.dragging = null;
      await blLoad();
    } catch (err) {
      blFail(err);
    }
  });

  BL.root.addEventListener('click', (e) => {
    const move = e.target.closest('[data-bl-move]');
    if (move) {
      blOpenMove(move.getAttribute('data-bl-move'));
      return;
    }
    const start = e.target.closest('[data-bl-start]');
    if (start) {
      BL.starting = start.getAttribute('data-bl-start');
      document.getElementById('bl-start-from').value = blDate(0);
      document.getElementById('bl-start-to').value = blDate(13);
      JackilModal.open('bl-start-modal');
      return;
    }
    const complete = e.target.closest('[data-bl-complete]');
    if (complete) {
      blComplete(complete.getAttribute('data-bl-complete'));
      return;
    }
    const edit = e.target.closest('[data-bl-edit]');
    if (edit) blOpenSprint(edit.getAttribute('data-bl-edit'));
  });
}

function blOpenMove(issueId) {
  BL.moving = issueId;
  const select = document.getElementById('bl-move-target');
  select.innerHTML = BL.data.sprints
    .map((sprint) => `<option value="${escAttr(sprint.id)}">${escHtml(sprint.name)}</option>`)
    .join('');
  select.insertAdjacentHTML('beforeend', '<option value="">Backlog</option>');
  document.getElementById('bl-move-pos').value = 'top';
  JackilModal.open('bl-move-modal');
}

async function blMoveOk() {
  const target = document.getElementById('bl-move-target').value;
  const list = BL.root.querySelector(`.bl-list[data-sprint="${CSS.escape(target)}"]`);
  const first = list ? list.querySelector('.bl-row') : null;
  const before =
    document.getElementById('bl-move-pos').value === 'top' && first
      ? first.getAttribute('data-issue-id')
      : null;
  try {
    await apiJson(blUrl('data-rank-url'), {
      method: 'POST',
      body: JSON.stringify({ issue: BL.moving, before, sprint: target || null }),
    });
    JackilModal.close();
    await blLoad();
  } catch (err) {
    blFail(err);
  }
}

async function blStartOk() {
  try {
    await apiJson(`/projects/${blUrl('data-project')}/sprints/${BL.starting}/start/`, {
      method: 'POST',
      body: JSON.stringify({
        start_date: document.getElementById('bl-start-from').value,
        end_date: document.getElementById('bl-start-to').value,
      }),
    });
    JackilModal.close();
    await blLoad();
  } catch (err) {
    blFail(err);
  }
}

async function blComplete(sprintId) {
  const sprint = blFindSprint(sprintId);
  if (!sprint) return;
  const next = BL.data.sprints.find((other) => other.state === 'planned');
  const ok = await JackilModal.confirm(
    `Complete ${sprint.name}? Open issues go to ${next ? next.name : 'the backlog'}.`,
    { confirmText: 'Complete', danger: true },
  );
  if (!ok) return;
  try {
    const body = await apiJson(`/projects/${blUrl('data-project')}/sprints/${sprintId}/complete/`, {
      method: 'POST',
      body: JSON.stringify({ move_open_to: next ? next.id : null }),
    });
    showToast(`${body.moved} issues moved`);
    await blLoad();
  } catch (err) {
    blFail(err);
  }
}

function blOpenSprint(sprintId) {
  BL.editing = sprintId;
  const sprint = sprintId ? blFindSprint(sprintId) : null;
  document.getElementById('bl-sprint-title').textContent = sprint ? 'Edit sprint' : 'Create sprint';
  document.getElementById('bl-sprint-name').value = sprint ? sprint.name : '';
  document.getElementById('bl-sprint-goal').value = sprint && sprint.goal ? sprint.goal : '';
  JackilModal.open('bl-sprint-modal');
}

async function blSprintOk() {
  const name = document.getElementById('bl-sprint-name').value.trim();
  const goal = document.getElementById('bl-sprint-goal').value.trim();
  try {
    if (BL.editing) {
      await apiJson(`/projects/${blUrl('data-project')}/sprints/${BL.editing}/edit/`, {
        method: 'POST',
        body: JSON.stringify({ name, goal }),
      });
    } else {
      await apiJson(blUrl('data-create-url'), { method: 'POST', body: JSON.stringify({ name, goal }) });
    }
    JackilModal.close();
    await blLoad();
  } catch (err) {
    blFail(err);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  BL.root = document.getElementById('bl-lists');
  if (!BL.root) return;
  blBind();
  blLoad();
});
