// sw.js
console.log('Hello from sw.js (v7)');

importScripts('https://storage.googleapis.com/workbox-cdn/releases/7.1.0/workbox-sw.js');

if (workbox) {
  console.log(`✅ Workbox v7 loaded`);

  // 1. Precache основных страниц и ресурсов
  workbox.precaching.precacheAndRoute([
    { url: '/', revision: null }, // revision: null — для URL с хешем или при использовании генерации
    { url: '/static/css/style.css', revision: null },
    { url: '/static/icons/dream.png', revision: null },
    { url: '/static/icons/dream_512.png', revision: null }
  ]);

  // 2. Кэширование статики: JS, CSS
  workbox.routing.registerRoute(
    /\.(?:js|css)$/i,
    new workbox.strategies.StaleWhileRevalidate({
      cacheName: 'static-resources',
      plugins: [
        new workbox.expiration.ExpirationPlugin({
          maxEntries: 50,
          maxAgeSeconds: 30 * 24 * 60 * 60, // 30 дней
        }),
      ],
    })
  );

  // 3. Кэширование изображений
  workbox.routing.registerRoute(
    /\.(?:png|gif|jpg|jpeg|svg|webp)$/i,
    new workbox.strategies.CacheFirst({
      cacheName: 'images',
      plugins: [
        new workbox.expiration.ExpirationPlugin({
          maxEntries: 100,
          maxAgeSeconds: 30 * 24 * 60 * 60,
        }),
      ],
    })
  );

  // sw.js — добавьте это после workbox.precaching.precacheAndRoute
    workbox.routing.registerRoute(
      ({ request }) => request.mode === 'navigate',
      new workbox.strategies.NetworkFirst({
        cacheName: 'pages',
        networkTimeoutSeconds: 3,
        plugins: [
          new workbox.expiration.ExpirationPlugin({
            maxEntries: 20,
          }),
        ],
      })
    );

  // 4. Google Fonts
  workbox.routing.registerRoute(
    /^https:\/\/fonts\.(?:googleapis|gstatic)\.com\/.*/i,
    new workbox.strategies.CacheFirst({
      cacheName: 'google-fonts',
      plugins: [
        new workbox.expiration.ExpirationPlugin({
          maxEntries: 30,
          maxAgeSeconds: 60 * 60 * 24 * 365, // 1 год
        }),
      ],
    })
  );

  // 5. API-запросы — НЕ кэшируем (чтобы не ломать логику чата)
  // Но можно добавить fallback на offline-сообщение:
  workbox.routing.registerRoute(
    ({ url }) => url.pathname.startsWith('/api/'),
    new workbox.strategies.NetworkOnly()
  );

  // 6. Fallback для навигации (offline-режим)
  workbox.routing.registerRoute(
    ({ request }) => request.mode === 'navigate',
    new workbox.strategies.NetworkFirst({
      cacheName: 'pages',
      networkTimeoutSeconds: 3,
      plugins: [
        new workbox.expiration.ExpirationPlugin({
          maxEntries: 20,
        }),
      ],
    })
  );

} else {
  console.warn(`⚠️ Workbox не загружен`);
}