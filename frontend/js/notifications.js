// ==============================================================================
// notifications.js - Gestor de Notificaciones Nativas de Escritorio (Web Push)
// Compatible con Windows 10/11, macOS, Android y iOS (PWA)
// ==============================================================================

(function () {
    let swRegistration = null;
    const LAST_NOTIF_KEY = 'enviobot_last_desktop_notif_time';
    const NOTIF_COOLDOWN_MS = 4 * 60 * 60 * 1000; // 4 horas entre alertas automáticas de escritorio

    // Inicializar Service Worker
    function initServiceWorker() {
        if ('serviceWorker' in navigator) {
            navigator.serviceWorker.register('/sw.js')
                .then(reg => {
                    swRegistration = reg;
                    console.log('[EnvioBot] Service Worker registrado con éxito.');
                })
                .catch(err => {
                    console.warn('[EnvioBot] No se pudo registrar Service Worker (modo local sin HTTPS o servidor):', err);
                });
        }
    }

    // Comprobar estado de permisos
    function getNotificationStatus() {
        if (!('Notification' in window)) {
            return 'unsupported';
        }
        return Notification.permission; // 'default', 'granted', 'denied'
    }

    // Solicitar permiso de notificaciones al usuario
    async function solicitarPermisoNotificaciones() {
        if (!('Notification' in window)) {
            alert('Tu navegador actual no soporta notificaciones nativas de escritorio.');
            return false;
        }

        try {
            const permission = await Notification.requestPermission();
            actualizarBotonNotificaciones();

            if (permission === 'granted') {
                mostrarNotificacion(
                    '¡Notificaciones Activas en EnvioBot Full!',
                    'Te avisaremos automáticamente cuando sea momento de pedir una nueva colecta.',
                    { test: true }
                );
                return true;
            } else if (permission === 'denied') {
                alert('Las notificaciones fueron bloqueadas en tu navegador. Podés reactivarlas haciendo clic en el candado junto a la URL.');
                return false;
            }
        } catch (e) {
            console.error('Error solicitando permisos:', e);
        }
        return false;
    }

    // Mostrar una notificación de escritorio nativa
    function mostrarNotificacion(titulo, cuerpo, datos = {}) {
        if (getNotificationStatus() !== 'granted') return;

        const options = {
            body: cuerpo,
            icon: '/img/enviobot_app_icon.png',
            badge: '/img/enviobot_app_icon.png',
            tag: 'enviobot-colecta-alerta',
            renotify: true,
            data: datos
        };

        // Si el Service Worker está activo, usarlo para mejor integración en Windows/Mac
        if (swRegistration && 'showNotification' in swRegistration) {
            swRegistration.showNotification(titulo, options);
        } else {
            // Fallback directo con la API Notification nativa
            try {
                const notif = new Notification(titulo, options);
                notif.onclick = function () {
                    window.focus();
                    if (typeof abrirModalColecta === 'function') {
                        abrirModalColecta();
                    }
                    this.close();
                };
            } catch (e) {
                console.warn('Error instanciando Notification:', e);
            }
        }
    }

    // Chequear stock y disparar notificación automática si corresponde
    function evaluarNotificacionAutomatica(items) {
        if (getNotificationStatus() !== 'granted' || !items || items.length === 0) return;

        // Verificar cooldown para no molestar repetidamente en la misma sesión
        const lastTime = parseInt(localStorage.getItem(LAST_NOTIF_KEY) || '0', 10);
        const now = Date.now();
        if (now - lastTime < NOTIF_COOLDOWN_MS) {
            return; // Ya se notificó hace menos de 4 horas
        }

        const criticals = items.filter(x => x.status === 'critical' || x.status === 'out_of_stock');
        const warnings = items.filter(x => x.status === 'warning');

        if (criticals.length > 0) {
            mostrarNotificacion(
                '🚨 Alarma Crítica de Quiebre — EnvioBot Full',
                `Tenés ${criticals.length} publicación(es) en riesgo inminente de quedarse sin stock. ¡Prepará el flete!`,
                { url: '/#colecta' }
            );
            localStorage.setItem(LAST_NOTIF_KEY, now.toString());
        } else if (warnings.length > 0) {
            mostrarNotificacion(
                '🚛 Momento de Pedir Colecta — EnvioBot Full',
                `Tenés ${warnings.length} publicación(es) en fecha límite para Mercado Envíos Full. Pedí el turno hoy.`,
                { url: '/#colecta' }
            );
            localStorage.setItem(LAST_NOTIF_KEY, now.toString());
        }
    }

    // Actualizar botón en la interfaz
    function actualizarBotonNotificaciones() {
        const btn = document.getElementById('btnToggleDesktopNotif');
        const statusText = document.getElementById('notifStatusText');
        if (!btn) return;

        const status = getNotificationStatus();
        if (status === 'granted') {
            btn.classList.add('active');
            btn.innerHTML = '<span>🔔 Notificaciones Activas</span>';
            if (statusText) statusText.textContent = 'Este equipo recibirá alertas nativas en pantalla.';
        } else if (status === 'denied') {
            btn.classList.remove('active');
            btn.innerHTML = '<span>🔕 Notificaciones Bloqueadas</span>';
            if (statusText) statusText.textContent = 'Bloqueadas en la configuración del navegador.';
        } else {
            btn.classList.remove('active');
            btn.innerHTML = '<span>🔔 Activar Notificaciones de Pantalla</span>';
            if (statusText) statusText.textContent = 'Permite recibir avisos automáticos aunque la pestaña esté minimizada.';
        }
    }

    // Exponer API global
    window.EnvioBotNotif = {
        init: function () {
            initServiceWorker();
            actualizarBotonNotificaciones();
        },
        requestPermission: solicitarPermisoNotificaciones,
        show: mostrarNotificacion,
        checkAuto: evaluarNotificacionAutomatica,
        getStatus: getNotificationStatus,
        updateUI: actualizarBotonNotificaciones
    };

    // Auto-arranque al cargar el DOM
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => window.EnvioBotNotif.init());
    } else {
        window.EnvioBotNotif.init();
    }
})();
