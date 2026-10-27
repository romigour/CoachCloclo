// Service worker : met en cache la coquille de l'app uniquement. Jamais /api.
const sw = self as unknown as {
  addEventListener: (type: string, cb: (e: any) => void) => void;
  skipWaiting: () => void;
  clients: { claim: () => Promise<void> };
};

const CACHE = "coach-shell-v1";
const SHELL = ["/", "/manifest.webmanifest", "/icon-192.png", "/icon-512.png"];

sw.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  sw.skipWaiting();
});

sw.addEventListener("activate", (e) => {
  e.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => sw.clients.claim()),
  );
});

sw.addEventListener("fetch", (e) => {
  const req: Request = e.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api")) return;
  // réseau d'abord (fichiers hachés, index à jour), cache en secours hors ligne
  e.respondWith(
    fetch(req)
      .then((res) => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return res;
      })
      .catch(async () => (await caches.match(req)) ?? (await caches.match("/")) ?? Response.error()),
  );
});
