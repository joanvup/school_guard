(function () {
    const DEFAULT_TIMEOUT_MS = 12000;

    window.apiFetch = async function (url, options = {}, timeoutMs = DEFAULT_TIMEOUT_MS) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeoutMs);
        const init = { credentials: 'same-origin', ...options, signal: controller.signal };

        try {
            const response = await fetch(url, init);
            let data = null;
            const contentType = response.headers.get('content-type') || '';
            if (contentType.includes('application/json')) {
                try {
                    data = await response.json();
                } catch (error) {
                    data = null;
                }
            }
            return { response, data };
        } finally {
            clearTimeout(timer);
        }
    };

    window.apiErrorMessage = function (data, fallback = 'Error de conexión con el servidor') {
        if (!data) return fallback;
        if (typeof data.message === 'string' && data.message) return data.message;
        if (typeof data.detail === 'string') return data.detail;
        if (Array.isArray(data.detail) && data.detail.length) {
            return data.detail[0].msg || fallback;
        }
        return fallback;
    };

    window.playFeedbackSound = function (success) {
        try {
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            if (!AudioContext) return;
            window.__feedbackAudioCtx = window.__feedbackAudioCtx || new AudioContext();
            const ctx = window.__feedbackAudioCtx;
            if (ctx.state === 'suspended') ctx.resume();
            const oscillator = ctx.createOscillator();
            const gain = ctx.createGain();
            oscillator.connect(gain);
            gain.connect(ctx.destination);
            oscillator.type = 'sine';
            oscillator.frequency.value = success ? 880 : 220;
            gain.gain.setValueAtTime(0.12, ctx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.25);
            oscillator.start();
            oscillator.stop(ctx.currentTime + 0.25);
        } catch (error) {
            // El navegador puede bloquear audio sin interacción previa.
        }
    };
})();
