(function () {
    const meta = document.querySelector('meta[name="csrf-token"]');
    const token = meta ? meta.content : '';
    const originalFetch = window.fetch.bind(window);

    window.fetch = function (input, init) {
        init = init ? { ...init } : {};
        const method = (init.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
        if (!['GET', 'HEAD', 'OPTIONS', 'TRACE'].includes(method)) {
            const headers = new Headers(init.headers || (input instanceof Request ? input.headers : undefined));
            headers.set('X-CSRF-Token', token);
            init.headers = headers;
        }
        return originalFetch(input, init);
    };
})();

document.addEventListener('error', (event) => {
    const image = event.target;
    if (!(image instanceof HTMLImageElement)) return;
    const fallback = image.dataset.fallback;
    if (!fallback || image.dataset.fallbackApplied === 'true') return;
    image.dataset.fallbackApplied = 'true';
    image.src = fallback;
}, true);

document.addEventListener('DOMContentLoaded', () => {
    const menuToggle = document.getElementById('menu-toggle');
    const menu = document.getElementById('menu');
    if (menuToggle && menu) {
        menuToggle.addEventListener('click', () => menu.classList.toggle('hidden'));
    }
});

if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/static/sw.js')
            .then((registration) => console.log('SW registrado con alcance:', registration.scope))
            .catch((error) => console.warn('SW fallo al registrar:', error));
    });
}
