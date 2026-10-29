const THEMES = ['dark', 'light', 'river', 'ink'];
const THEME_LABELS = { dark: 'Dark', light: 'Paper', river: 'River', ink: 'Ink' };

function getCsrf() {
  const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : '';
}

function escHtml(str) {
  const d = document.createElement('div');
  d.textContent = str == null ? '' : String(str);
  return d.innerHTML;
}

function escAttr(str) {
  return String(str == null ? '' : str)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

async function apiJson(url, opts) {
  const resp = await fetch(url, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrf() },
    ...opts,
  });
  const body = resp.status === 204 ? {} : await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const err = new Error(body.detail || body.error || 'Request failed');
    err.status = resp.status;
    err.body = body;
    throw err;
  }
  return body;
}

function showToast(message, type) {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'toast-container';
    container.setAttribute('aria-live', 'polite');
    document.body.appendChild(container);
  }
  const toast = document.createElement('div');
  toast.className = 'toast ' + (type || '');
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
}

function _resolvedTheme(mode) {
  if (mode === 'system') {
    return matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  }
  return THEMES.includes(mode) ? mode : 'dark';
}

function setTheme(mode) {
  if (mode !== 'system' && !THEMES.includes(mode)) mode = 'dark';
  const resolved = _resolvedTheme(mode);
  document.documentElement.setAttribute('data-theme', resolved);
  try { localStorage.setItem('sqsy-theme', mode); } catch (e) {}
  const toggle = document.getElementById('theme-toggle');
  if (toggle) toggle.dataset.tip = 'Theme: ' + THEME_LABELS[resolved];
  document.querySelectorAll('[data-theme-set]').forEach((btn) => {
    btn.setAttribute('aria-pressed', btn.dataset.themeSet === resolved ? 'true' : 'false');
  });
  const followSystem = document.getElementById('follow-system');
  if (followSystem) followSystem.setAttribute('aria-checked', mode === 'system' ? 'true' : 'false');
  document.dispatchEvent(new CustomEvent('jackil:theme', { detail: { theme: resolved } }));
}

function storedThemeMode() {
  try { return localStorage.getItem('sqsy-theme') || 'dark'; } catch (e) { return 'dark'; }
}

function setReduceMotion(on) {
  document.documentElement.classList.toggle('rm-sim', on);
  try {
    if (on) localStorage.setItem('jackil-reduce-motion', '1');
    else localStorage.removeItem('jackil-reduce-motion');
  } catch (e) {}
  document.querySelectorAll('[data-rm-toggle]').forEach((btn) => {
    btn.setAttribute('aria-checked', on ? 'true' : 'false');
  });
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme') || 'dark';
  const i = THEMES.indexOf(current);
  setTheme(THEMES[(i + 1) % THEMES.length]);
}

function _sidebarLabels() {
  document.querySelectorAll('.sidebar .sidebar-icon[data-tip]').forEach((icon) => {
    if (icon.querySelector('.sidebar-label')) return;
    const label = document.createElement('span');
    label.className = 'sidebar-label';
    label.textContent = icon.dataset.tip.replace(/\s*\(.*\)\s*$/, '').replace(/:.*$/, '');
    icon.appendChild(label);
  });
}

function _applySidebarToggle(expanded) {
  const btn = document.getElementById('sidebar-toggle');
  if (!btn) return;
  const words = expanded ? 'Hide page names' : 'Show page names';
  btn.setAttribute('aria-expanded', expanded ? 'true' : 'false');
  btn.setAttribute('aria-label', words);
  btn.dataset.tip = words;
  const label = btn.querySelector('.sidebar-label');
  if (label) label.textContent = expanded ? 'Collapse' : 'Expand';
}

function toggleSidebar() {
  const expanded = document.documentElement.getAttribute('data-sidebar') !== 'expanded';
  if (expanded) document.documentElement.setAttribute('data-sidebar', 'expanded');
  else document.documentElement.removeAttribute('data-sidebar');
  try { localStorage.setItem('jackil-sidebar', expanded ? 'expanded' : 'collapsed'); } catch (e) {}
  _applySidebarToggle(expanded);
}

/* Times arrive as labelled UTC inside <time data-local>; show them in the
   reader's own zone, keeping the UTC text as the hover title. */
const _LOCAL_TIME_FORMATS = {
  datetime: { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' },
  short: { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' },
};

function localTimes(root) {
  (root || document).querySelectorAll('time[data-local]').forEach((el) => {
    const when = new Date(el.getAttribute('datetime'));
    if (Number.isNaN(when.getTime())) return;
    const format = _LOCAL_TIME_FORMATS[el.dataset.local] || _LOCAL_TIME_FORMATS.datetime;
    if (!el.title) el.title = el.textContent;
    el.textContent = when.toLocaleString(undefined, format);
  });
}

document.addEventListener('DOMContentLoaded', () => {
  localTimes(document);
  const expanded = document.documentElement.getAttribute('data-sidebar') === 'expanded';
  _sidebarLabels();
  _applySidebarToggle(expanded);

  const themeToggle = document.getElementById('theme-toggle');
  if (themeToggle) {
    themeToggle.dataset.tip =
      'Theme: ' + THEME_LABELS[document.documentElement.getAttribute('data-theme') || 'dark'];
  }

  const bind = (el, fn) => {
    if (!el) return;
    el.addEventListener('click', fn);
    el.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        fn();
      }
    });
  };
  bind(document.getElementById('sidebar-toggle'), toggleSidebar);
  bind(themeToggle, toggleTheme);

  document.querySelectorAll('[data-theme-set]').forEach((btn) => {
    btn.addEventListener('click', () => setTheme(btn.dataset.themeSet));
  });

  const followSystem = document.getElementById('follow-system');
  if (followSystem) {
    followSystem.addEventListener('click', () => {
      const following = followSystem.getAttribute('aria-checked') === 'true';
      setTheme(following ? _resolvedTheme(storedThemeMode()) : 'system');
    });
  }

  document.querySelectorAll('[data-rm-toggle]').forEach((btn) => {
    btn.addEventListener('click', () => {
      setReduceMotion(!document.documentElement.classList.contains('rm-sim'));
    });
  });

  const mode = storedThemeMode();
  setTheme(mode);
  if (mode === 'system') {
    matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => {
      setTheme(storedThemeMode());
    });
  }
});
