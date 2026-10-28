/* Project reports page (M5 p05b). Each card owns one endpoint: the body's
   data-url is fetched, unwrapped from its envelope, and handed to the widget
   renderer for the shape the server named. Selects re-paint their own card. */

function rpParam(name) {
  const el = document.getElementById(name);
  return el ? el.value : '';
}

function rpUrl(body) {
  const base = body.getAttribute('data-url');
  const kind = body.getAttribute('data-report');
  const params = {};
  if (kind === 'burndown') params.sprint = rpParam('rp-sprint');
  if (kind === 'flow') params.days = rpParam('rp-days');
  if (kind === 'cost') params.by = rpParam('rp-by');
  const query = new URLSearchParams(params).toString();
  return query ? base + '?' + query : base;
}

async function rpPaint(body) {
  let env;
  try {
    env = await apiJson(rpUrl(body));
  } catch (err) {
    body.innerHTML = '<span class="muted-note">Couldn\u2019t load this report.</span>';
    return;
  }
  const render = WIDGET_SHAPES[env.shape];
  if (!render) {
    body.innerHTML = '<span class="muted-note">Couldn\u2019t load this report.</span>';
    return;
  }
  try {
    render(body, env.data);
  } catch (err) {
    body.innerHTML = '<span class="muted-note">Couldn\u2019t load this report.</span>';
  }
}

function rpOn(id, handler) {
  const el = document.getElementById(id);
  if (el) el.addEventListener('change', handler);
}

document.addEventListener('DOMContentLoaded', () => {
  const bodies = {};
  document.querySelectorAll('[data-report]').forEach((body) => {
    bodies[body.getAttribute('data-report')] = body;
    rpPaint(body);
  });

  rpOn('rp-sprint', () => bodies.burndown && rpPaint(bodies.burndown));
  rpOn('rp-days', () => bodies.flow && rpPaint(bodies.flow));
  rpOn('rp-by', () => {
    if (bodies.cost) rpPaint(bodies.cost);
    const link = document.getElementById('rp-csv');
    if (link) link.href = link.href.split('?')[0] + '?by=' + encodeURIComponent(rpParam('rp-by'));
  });
});
