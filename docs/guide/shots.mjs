// Captures du guide, prises sur une appli CoachCloclo déjà lancée (lecture seule).
// Usage : node --experimental-websocket docs/guide/shots.mjs [nom…]
//   COACH_URL (défaut http://127.0.0.1:8765), CHROME (chemin de chrome.exe / msedge.exe),
//   SHOTS_OUT (dossier de sortie, défaut docs/guide/img), SHOTS_FULL=1 (pleine page, pour repérer).
import { spawn } from 'node:child_process';
import { mkdtempSync, writeFileSync, mkdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const BASE = process.env.COACH_URL || 'http://127.0.0.1:8765';
const OUT = process.env.SHOTS_OUT || join(dirname(fileURLToPath(import.meta.url)), 'img');
const CHROME = process.env.CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const FULL = process.env.SHOTS_FULL === '1';
const DESK = [1080, 675];
const PHONE = [390, 844];

// hash : écran ; waitFor : sélecteur qui prouve le chargement ;
// scrollTo : élément amené en haut ; clip : capture limitée à l'élément (avec marge).
// click : texte exact d'un bouton à cliquer avant la capture (ouvre un formulaire, ne valide rien).
// Un sélecteur peut être 'text=…' : premier élément dont le texte commence par …
export const SHOTS = [
  { name: 'week', hash: '#/week', waitFor: 'main h1' },
  { name: 'goals', hash: '#/goal', waitFor: 'ul.goals' },
  { name: 'goals-close', hash: '#/goal', waitFor: 'ul.goals', clip: 'ul.goals' },
  { name: 'event', hash: '#/week', waitFor: 'main h1', click: 'Signaler un imprévu' },
  { name: 'race', hash: '#/race/3', waitFor: 'table[aria-label="Segments"]' },
  { name: 'stats-top', hash: '#/stats', waitFor: 'main h1' },
  { name: 'stats-run', hash: '#/stats', waitFor: 'main h1', scrollTo: 'text=Course à pied' },
  { name: 'stats-records', hash: '#/stats', waitFor: 'main h1', scrollTo: 'text=Records' },
  { name: 'stats-dark', hash: '#/stats', waitFor: 'main h1', scheme: 'dark' },
  { name: 'm-week', hash: '#/week', waitFor: 'main h1', viewport: PHONE, mobile: true, scrollTo: 'main' },
  { name: 'm-stats', hash: '#/stats', waitFor: 'main h1', viewport: PHONE, mobile: true, scrollTo: 'main' },
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function cdp(port) {
  for (let i = 0; i < 50; i++) {
    try {
      const tabs = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
      const page = tabs.find((t) => t.type === 'page');
      if (page) {
        const ws = new WebSocket(page.webSocketDebuggerUrl);
        await new Promise((ok, ko) => { ws.onopen = ok; ws.onerror = ko; });
        let id = 0;
        const waiting = new Map();
        ws.onmessage = (m) => {
          const msg = JSON.parse(m.data);
          if (msg.method === 'Fetch.requestPaused') onPaused(msg.params);
          if (msg.id && waiting.has(msg.id)) {
            const { ok, ko } = waiting.get(msg.id);
            waiting.delete(msg.id);
            msg.error ? ko(new Error(msg.error.message)) : ok(msg.result);
          }
        };
        const send = (method, params = {}) => new Promise((ok, ko) => {
          waiting.set(++id, { ok, ko });
          ws.send(JSON.stringify({ id, method, params }));
        });
        // Lecture seule : toute requête d'écriture (POST, PUT, PATCH, DELETE) reçoit une réponse vide
        // sans atteindre l'appli. Évite la synchro Garmin et l'analyse Claude lancées à chaque chargement.
        const onPaused = (p) => {
          if (p.request.method === 'GET') return send('Fetch.continueRequest', { requestId: p.requestId });
          console.log(`  bloqué : ${p.request.method} ${p.request.url.replace(BASE, '')}`);
          return send('Fetch.fulfillRequest', { requestId: p.requestId, responseCode: 200,
            responseHeaders: [{ name: 'Content-Type', value: 'application/json' }], body: Buffer.from('{}').toString('base64') });
        };
        await send('Fetch.enable', { patterns: [{ urlPattern: BASE + '/api/*' }] });
        return { send, close: () => ws.close() };
      }
    } catch { /* Chrome pas encore prêt */ }
    await sleep(200);
  }
  throw new Error('Chrome ne répond pas sur le port de débogage');
}

// Code exécuté dans la page : trouve un élément par sélecteur CSS ou par 'text=…'.
const FIND = `(sel) => {
  if (!sel.startsWith('text=')) return document.querySelector(sel);
  const t = sel.slice(5);
  let best = null;
  for (const el of document.querySelectorAll('main *')) {
    if ((el.innerText || '').trim().startsWith(t)) best = el;  // le plus profond gagne
  }
  if (!best) return null;
  // remonte jusqu'à la carte / section qui le contient
  return best.closest('section, article, .card, li') || best;
}`;

async function evalJs(send, expr) {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.text);
  return r.result.value;
}

async function shoot(send, s) {
  const [w, h] = s.viewport || DESK;
  await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 2, mobile: !!s.mobile });
  await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: s.scheme || 'light' }] });
  await send('Page.navigate', { url: 'about:blank' });  // repart d'une page neuve (ni dialogue ni défilement)
  await sleep(200);
  await send('Page.navigate', { url: BASE + '/' + s.hash });
  const found = await evalJs(send, `(async () => { const f = ${FIND};
    for (let i = 0; i < 150; i++) { if (f(${JSON.stringify(s.waitFor)})) return true; await new Promise(r => setTimeout(r, 100)); }
    return false; })()`);
  if (!found) throw new Error(`${s.name} : ${s.waitFor} introuvable`);
  // attend la fin des bandeaux « Synchronisation… » / « Analyse… » et des chargements
  await evalJs(send, `(async () => { for (let i = 0; i < 300; i++) {
    if (!document.querySelector('.busy') && !/Synchronisation…|Chargement/.test(document.body.innerText)) return;
    await new Promise(r => setTimeout(r, 100)); } })()`);
  await sleep(1500);  // graphiques et requêtes secondaires
  if (s.click) {
    const ok = await evalJs(send, `(() => { const b = [...document.querySelectorAll('button')]
      .find(b => b.innerText.trim() === ${JSON.stringify(s.click)}); if (b) b.click(); return !!b; })()`);
    if (!ok) throw new Error(`${s.name} : bouton ${s.click} introuvable`);
    await sleep(800);
  }
  const target = s.clip || s.scrollTo;
  let clip;
  if (target) {
    const rect = await evalJs(send, `(() => { const el = (${FIND})(${JSON.stringify(target)});
      if (!el) return null; el.scrollIntoView({ block: 'start' }); window.scrollBy(0, -16);
      const r = el.getBoundingClientRect(); return { x: r.x, y: r.y + window.scrollY, width: r.width, height: r.height }; })()`);
    if (!rect) throw new Error(`${s.name} : ${target} introuvable`);
    await sleep(500);
    if (s.clip) {
      const m = 12;
      clip = { x: Math.max(0, rect.x - m), y: Math.max(0, rect.y - m), width: rect.width + 2 * m, height: rect.height + 2 * m, scale: 1 };
    }
  }
  const params = { format: 'jpeg', quality: Number(process.env.SHOTS_QUALITY || 80) };
  if (clip) { params.clip = clip; params.captureBeyondViewport = true; }
  if (FULL && !clip) params.captureBeyondViewport = true;
  if (FULL && !clip) {
    const height = await evalJs(send, 'document.documentElement.scrollHeight');
    await send('Emulation.setDeviceMetricsOverride', { width: w, height, deviceScaleFactor: 1, mobile: !!s.mobile });
    await evalJs(send, 'window.scrollTo(0, 0)');
    await sleep(500);
  }
  const { data } = await send('Page.captureScreenshot', params);
  const file = join(OUT, `${s.name}.jpg`);
  writeFileSync(file, Buffer.from(data, 'base64'));
  console.log(`${s.name} -> ${file} (${Math.round(Buffer.from(data, 'base64').length / 1024)} Ko)`);
}

const wanted = process.argv.slice(2);
const list = wanted.length ? SHOTS.filter((s) => wanted.includes(s.name)) : SHOTS;
mkdirSync(OUT, { recursive: true });
const profile = mkdtempSync(join(tmpdir(), 'coach-shots-'));
const port = 9333;
const chrome = spawn(CHROME, ['--headless=new', `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`,
  '--hide-scrollbars', '--no-first-run', 'about:blank'], { stdio: 'ignore' });
let failed = 0;
try {
  const { send, close } = await cdp(port);
  await send('Page.enable');
  await send('Runtime.enable');
  for (const s of list) {
    try { await shoot(send, s); } catch (e) { failed++; console.error(`ÉCHEC ${e.message}`); }
  }
  close();
} finally {
  chrome.kill();
  await sleep(500);
  try { rmSync(profile, { recursive: true, force: true }); } catch { /* profil verrouillé */ }
}
process.exit(failed ? 1 : 0);
