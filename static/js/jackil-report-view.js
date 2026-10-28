/* Saved-report page. Each card's body carries its index; the envelope from
   the report's data endpoint is handed to the shared shape renderer
   (jackil-widgets.js), the same five painters the dashboard grid uses. */

async function rvPaint(grid, body) {
  const url = '/reports/api/' + grid.getAttribute('data-report')
    + '/data/' + body.getAttribute('data-index') + '/';
  let env;
  try {
    env = await apiJson(url);
  } catch (err) {
    body.innerHTML = '<span class="muted-note">Couldn\u2019t load this card.</span>';
    return;
  }
  const render = WIDGET_SHAPES[env.shape];
  if (!render) {
    body.innerHTML = '<span class="muted-note">Couldn\u2019t load this card.</span>';
    return;
  }
  try {
    render(body, env.data);
  } catch (err) {
    body.innerHTML = '<span class="muted-note">Couldn\u2019t load this card.</span>';
  }
}

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.rv-grid').forEach((grid) => {
    grid.querySelectorAll('.rv-body').forEach((body) => rvPaint(grid, body));
  });
});
