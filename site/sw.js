// ネットワーク優先（ブラウザの HTTP キャッシュも使わず毎回サーバーに確認）、オフライン時は前回分を表示
const CACHE = "r573-v11";
const SHELL = ["./", "index.html", "style.css", "app.js", "manifest.webmanifest", "icons/icon-192.png", "icons/icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.includes("/data/")) {
    e.respondWith(
      fetch(e.request, { cache: "no-cache" })
        .then((r) => {
          const copy = r.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
          return r;
        })
        .catch(() => caches.match(e.request, { ignoreSearch: true }))
    );
    return;
  }
  // アプリ本体もネットワーク優先（更新をすぐ反映）。オフライン時のみキャッシュ
  e.respondWith(
    fetch(e.request, { cache: "no-cache" })
      .then((r) => {
        const copy = r.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return r;
      })
      .catch(() => caches.match(e.request, { ignoreSearch: true }))
  );
});
