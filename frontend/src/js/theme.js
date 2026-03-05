/*
 * ClawSafe Pay — Dashboard Theme Switcher
 * Manages theme toggling, persistence, and the theme picker menu.
 */

export function toggleThemeMenu() {
  document.getElementById('themeMenu').classList.toggle('open');
}

export function setTheme(name) {
  document.documentElement.setAttribute('data-theme', name);
  localStorage.setItem('clawsafe-theme', name);
  document.querySelectorAll('.theme-opt').forEach(o =>
    o.classList.toggle('active', o.dataset.theme === name)
  );
  document.getElementById('themeMenu').classList.remove('open');
}

export function initTheme() {
  const saved = localStorage.getItem('clawsafe-theme') || 'midnight';
  document.documentElement.setAttribute('data-theme', saved);
  document.querySelectorAll('.theme-opt').forEach(o =>
    o.classList.toggle('active', o.dataset.theme === saved)
  );
}

export function setupThemeClickOutside() {
  document.addEventListener('click', e => {
    if (!e.target.closest('.theme-wrap')) {
      document.getElementById('themeMenu').classList.remove('open');
    }
  });
}

// Expose to inline onclick handlers
window.toggleThemeMenu = toggleThemeMenu;
window.setTheme = setTheme;
