// KaTeX for the wiki. The server renderer already marked every formula with
// .math.inline / .math.block, so this only has to run KaTeX over what it finds —
// no delimiter scan (auto-render) needed, and none wanted: `$` in prose is a
// price or a shell prompt, and the renderer already decided which ones are math.
function renderMath(root) {
  if (typeof katex === 'undefined' || !root) return;
  root.querySelectorAll('.math.inline, .math.block').forEach((el) => {
    // throwOnError: false leaves the source on the page when a formula is
    // malformed, instead of throwing and stopping every later render.
    katex.render(el.textContent, el, {
      displayMode: el.classList.contains('block'),
      throwOnError: false,
    });
  });
}

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-markdown]').forEach(renderMath);
});
