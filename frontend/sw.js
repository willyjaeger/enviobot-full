// ==============================================================================
// sw.js - Service Worker de EnvioBot Full
// Gestiona notificaciones nativas de escritorio y eventos en segundo plano
// ==============================================================================

const CACHE_NAME = 'enviobot-full-v1';
const ASSETS_TO_CACHE = [
  '/',
  '/index.html',
  '/css/style.css',
  '/js/app.js',
  '/js/theme.js',
  '/js/notifications.js',
  '/img/enviobot_app_icon.png',
  '/img/cajita_esquematica.svg'
];

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

// Manejo de clic en la notificación del sistema
self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  // Enfocar ventana abierta o abrir una nueva si está cerrada
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (let client of clientList) {
        if ('focus' in client) {
          return client.focus();
        }
      }
      if (clients.openWindow) {
        return clients.openWindow('/#colecta');
      }
    })
  );
});

// Manejo de eventos Push remotos (Web Push API)
self.addEventListener('push', (event) => {
  let data = {
    title: 'EnvioBot Full — Alerta de Stock',
    body: 'Tenés publicaciones en fecha límite de reposición.',
    icon: '/img/enviobot_app_icon.png',
    badge: '/img/enviobot_app_icon.png'
  };

  if (event.data) {
    try {
      data = Object.assign(data, event.data.json());
    } catch (e) {
      data.body = event.data.text();
    }
  }

  const options = {
    body: data.body,
    icon: data.icon || '/img/enviobot_app_icon.png',
    badge: data.badge || '/img/enviobot_app_icon.png',
    vibrate: [200, 100, 200],
    data: data.data || { url: '/' },
    tag: 'enviobot-alert',
    renotify: true
  };

  event.waitUntil(
    self.registration.showNotification(data.title, options)
  );
});
