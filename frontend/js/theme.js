// theme.js - Manejo del tema oscuro/claro (alto contraste) sin parpadeo

function getSavedTheme() {
    return localStorage.getItem('enviobot_full_theme') || localStorage.getItem('enviobot_theme') || 'dark';
}

function applyTheme(theme) {
    if (theme === 'light') {
        document.documentElement.setAttribute('data-theme', 'light');
    } else {
        document.documentElement.removeAttribute('data-theme');
    }
    updateThemeToggleUI(theme);
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
    const next = current === 'light' ? 'dark' : 'light';
    localStorage.setItem('enviobot_full_theme', next);
    applyTheme(next);
}

function updateThemeToggleUI(theme) {
    const label = document.getElementById('themeLabel');
    const icon = document.getElementById('themeIcon');
    if (!label) return;

    if (theme === 'light') {
        label.textContent = 'Modo oscuro';
        if (icon) {
            icon.innerHTML = '<path d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z"></path>';
        }
    } else {
        label.textContent = 'Modo claro';
        if (icon) {
            icon.innerHTML = '<path d="M20 14.5A8.5 8.5 0 019.5 4 8.5 8.5 0 1020 14.5z"></path>';
        }
    }
}

// Aplicar al cargar
document.addEventListener('DOMContentLoaded', () => {
    applyTheme(getSavedTheme());
});
