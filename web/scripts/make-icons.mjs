// Génère le logo et les icônes de CoachCloclo à partir d'un même dessin : un « C » en virage
// de piste d'athlétisme (demi-cercle prolongé de deux lignes droites, couloirs tracés), blanc
// sur fond pétrole. Sorties : public/logo.svg, public/icon-192.png, public/icon-512.png et
// packaging/windows/coachcloclo.ico (exe, installateur, icône près de l'horloge).
import { deflateSync } from "node:zlib";
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const pub = join(root, "public");
const ico = join(root, "..", "packaging", "windows", "coachcloclo.ico");

// --- le dessin, en coordonnées 0..1 -----------------------------------------------------------

const BG = [0x24, 0x5b, 0x4f]; // --accent
const FG = [0xff, 0xff, 0xff];
const CORNER = 0.22; // rayon des coins du fond
const R_OUT = 0.34; // bord extérieur de la piste
const R_IN = 0.18; // bord intérieur
const STRAIGHT = 0.14; // longueur des lignes droites à droite du centre
// centre du virage, décalé pour que le « C » (de cx - R_OUT à cx + STRAIGHT) soit centré
const CX = 0.5 - (STRAIGHT - R_OUT) / 2;
const CY = 0.5;
const LANES = 3;
const LINE = 0.018; // épaisseur des lignes de couloir
const lanes = Array.from({ length: LANES - 1 }, (_, i) => R_IN + ((R_OUT - R_IN) * (i + 1)) / LANES);

/** Distance au centre de la piste : au rayon dans le virage, à l'horizontale sur les droites. */
function trackRadius(x, y) {
  const dx = x - CX, dy = y - CY;
  if (dx <= 0) return Math.hypot(dx, dy);
  if (dx <= STRAIGHT) return Math.abs(dy);
  return Infinity;
}

function insideBackground(x, y) {
  const qx = Math.max(Math.abs(x - 0.5) - (0.5 - CORNER), 0);
  const qy = Math.max(Math.abs(y - 0.5) - (0.5 - CORNER), 0);
  return Math.hypot(qx, qy) <= CORNER;
}

/** Couleur d'un point : null hors du fond ; couloirs omis en petit (illisibles sous 48 px). */
function sample(x, y, withLanes) {
  if (!insideBackground(x, y)) return null;
  const d = trackRadius(x, y);
  if (d < R_IN || d > R_OUT) return BG;
  if (withLanes && lanes.some((r) => Math.abs(d - r) < LINE / 2)) return BG;
  return FG;
}

// --- rendu PNG (RGBA, anticrénelage par suréchantillonnage) --------------------------------------

function crc32(buf) {
  let c, crc = ~0;
  for (let n = 0; n < buf.length; n++) {
    c = (crc ^ buf[n]) & 0xff;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    crc = (crc >>> 8) ^ c;
  }
  return ~crc >>> 0;
}

function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([len, body, crc]);
}

function png(size) {
  const SS = 4;
  const withLanes = size >= 48;
  const rows = [];
  for (let y = 0; y < size; y++) {
    const row = Buffer.alloc(1 + size * 4);
    for (let x = 0; x < size; x++) {
      let r = 0, g = 0, b = 0, a = 0;
      for (let sy = 0; sy < SS; sy++) {
        for (let sx = 0; sx < SS; sx++) {
          const c = sample((x + (sx + 0.5) / SS) / size, (y + (sy + 0.5) / SS) / size, withLanes);
          if (!c) continue;
          r += c[0]; g += c[1]; b += c[2]; a++;
        }
      }
      // couleurs non prémultipliées : moyenne sur les seuls échantillons couverts
      if (a) row.set([r / a, g / a, b / a, (255 * a) / (SS * SS)].map(Math.round), 1 + x * 4);
    }
    rows.push(row);
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8; // profondeur
  ihdr[9] = 6; // RGBA
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", deflateSync(Buffer.concat(rows))),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

/** ICO multi-tailles dont chaque image est un PNG (format admis depuis Windows Vista). */
function icoFile(sizes) {
  const images = sizes.map(png);
  const header = Buffer.alloc(6);
  header.writeUInt16LE(1, 2); // type : icône
  header.writeUInt16LE(sizes.length, 4);
  let offset = 6 + 16 * sizes.length;
  const entries = sizes.map((size, i) => {
    const e = Buffer.alloc(16);
    e[0] = size >= 256 ? 0 : size; // 0 signifie 256
    e[1] = size >= 256 ? 0 : size;
    e.writeUInt16LE(1, 4); // plans
    e.writeUInt16LE(32, 6); // bits par pixel
    e.writeUInt32LE(images[i].length, 8);
    e.writeUInt32LE(offset, 12);
    offset += images[i].length;
    return e;
  });
  return Buffer.concat([header, ...entries, ...images]);
}

// --- SVG (barre latérale) ----------------------------------------------------------------------

function svg() {
  const S = 100;
  const n = (v) => +(v * S).toFixed(2);
  const hex = (c) => "#" + c.map((v) => v.toString(16).padStart(2, "0")).join("");
  // même tracé que trackRadius : ligne droite, demi-cercle à gauche, ligne droite
  const track = (r) =>
    `M${n(CX + STRAIGHT)} ${n(CY - r)}H${n(CX)}A${n(r)} ${n(r)} 0 0 0 ${n(CX)} ${n(CY + r)}H${n(CX + STRAIGHT)}`;
  const mid = (R_IN + R_OUT) / 2;
  return [
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${S} ${S}">`,
    `<rect width="${S}" height="${S}" rx="${n(CORNER)}" fill="${hex(BG)}"/>`,
    `<path d="${track(mid)}" fill="none" stroke="${hex(FG)}" stroke-width="${n(R_OUT - R_IN)}"/>`,
    ...lanes.map((r) => `<path d="${track(r)}" fill="none" stroke="${hex(BG)}" stroke-width="${n(LINE)}"/>`),
    `</svg>`,
    "",
  ].join("\n");
}

writeFileSync(join(pub, "logo.svg"), svg());
for (const size of [192, 512]) writeFileSync(join(pub, `icon-${size}.png`), png(size));
writeFileSync(ico, icoFile([16, 24, 32, 48, 64, 256]));
console.log("logo et icônes générés");
