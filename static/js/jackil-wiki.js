/* Wiki page tree, its filter, "On this page", and Copy link.
 *
 * The tree is server-rendered (templates/wiki/_tree.html): sections open and
 * close in place, and the filter hides pages that don't match while keeping
 * the parents of those that do, so a match is never shown out of context.
 */

const JackilWiki = {
  initTree(root) {
    root.addEventListener('click', (e) => {
      const toggle = e.target.closest('[data-wt-toggle]');
      if (!toggle) return;
      const item = toggle.closest('[data-wt-item]');
      const shut = item.classList.toggle('shut');
      toggle.setAttribute('aria-expanded', shut ? 'false' : 'true');
    });
  },

  initFilter(input, root) {
    const items = Array.from(root.querySelectorAll('[data-wt-item]'));
    input.addEventListener('input', () => {
      const term = input.value.trim().toLowerCase();
      // Children first, so a parent knows whether anything under it matched.
      items.slice().reverse().forEach((item) => {
        const link = item.querySelector(':scope > .wt-row .wt-link');
        const own = !term || (link && link.textContent.toLowerCase().includes(term));
        const kid = item.querySelector(':scope > .wt-kids [data-wt-item]:not(.wt-hidden)');
        item.classList.toggle('wt-hidden', !(own || kid));
        if (term && kid) item.classList.remove('shut');
      });
      root.classList.toggle('wt-filtering', !!term);
    });
  },

  slug(text, used) {
    let base = text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'section';
    let id = base;
    for (let n = 2; used.has(id) || document.getElementById(id); n += 1) id = base + '-' + n;
    used.add(id);
    return id;
  },

  initToc(toc, article) {
    const heads = Array.from(article.querySelectorAll('.markdown-body h2, .markdown-body h3'));
    if (heads.length < 2) return;
    const used = new Set();
    const links = heads.map((h) => {
      if (!h.id) h.id = this.slug(h.textContent, used);
      const a = document.createElement('a');
      a.href = '#' + h.id;
      a.textContent = h.textContent;
      a.className = h.tagName === 'H3' ? 'wk-toc-sub' : '';
      toc.appendChild(a);
      return a;
    });
    toc.hidden = false;
    if (!('IntersectionObserver' in window)) return;
    const seen = new Map();
    const spy = new IntersectionObserver((entries) => {
      entries.forEach((entry) => seen.set(entry.target, entry.isIntersecting));
      // The first heading on screen is the section being read.
      const at = heads.findIndex((h) => seen.get(h));
      if (at < 0) return;
      links.forEach((a, i) => a.classList.toggle('on', i === at));
    }, { rootMargin: '0px 0px -65% 0px' });
    heads.forEach((h) => spy.observe(h));
  },

  initCopy(btn) {
    btn.addEventListener('click', () => {
      const done = () => (typeof showToast === 'function' ? showToast('Link copied') : null);
      if (navigator.clipboard) navigator.clipboard.writeText(btn.dataset.wkCopy).then(done, () => {});
    });
  },
};

document.querySelectorAll('[data-wt-root]').forEach((root) => {
  JackilWiki.initTree(root);
  const scope = root.closest('.wk-side') || document;
  const input = scope.querySelector('[data-wt-filter]');
  if (input) JackilWiki.initFilter(input, root);
});
// Most pages open with their own title as a heading; the page already shows
// it above, so the copy in the body goes.
const wikiTitle = document.querySelector('.wk-title');
const wikiFirst = document.querySelector('.wk-article .markdown-body > :first-child');
if (wikiTitle && wikiFirst && wikiFirst.tagName === 'H1'
    && wikiFirst.textContent.trim().toLowerCase() === wikiTitle.textContent.trim().toLowerCase()) {
  wikiFirst.remove();
}
const wikiToc = document.querySelector('[data-wk-toc]');
const wikiArticle = document.querySelector('[data-wk-article]');
if (wikiToc && wikiArticle) JackilWiki.initToc(wikiToc, wikiArticle);
document.querySelectorAll('[data-wk-copy]').forEach((btn) => JackilWiki.initCopy(btn));
