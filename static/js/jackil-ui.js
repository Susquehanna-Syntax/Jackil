const THEMES = ['dark', 'light', 'river', 'ink'];
const THEME_LABELS = { dark: 'Dark', light: 'Paper', river: 'River', ink: 'Ink' };

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

document.addEventListener('DOMContentLoaded', () => {
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
