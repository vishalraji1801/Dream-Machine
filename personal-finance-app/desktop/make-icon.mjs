// Generates build/icon.png with no image dependencies — electron-builder
// converts this into the Windows .ico at package time.
import { deflateSync } from 'node:zlib';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const SIZE = 512;
const SAMPLES = 3; // supersampling grid per axis, for smooth edges

const BG = [0x2a, 0x78, 0xd6];
const FG = [0xff, 0xff, 0xff];

/** Squared distance from a point to a rect, i.e. rounded-rect coverage test. */
function insideRoundRect(x, y, x0, y0, x1, y1, r) {
  const dx = Math.max(x0 + r - x, 0, x - (x1 - r));
  const dy = Math.max(y0 + r - y, 0, y - (y1 - r));
  return dx * dx + dy * dy <= r * r;
}

const BAR_WIDTH = 64;
const BAR_GAP = 32;
const BASELINE = 424;
const HEIGHTS = [120, 184, 248, 312];
const FIRST_X = (SIZE - (HEIGHTS.length * BAR_WIDTH + (HEIGHTS.length - 1) * BAR_GAP)) / 2;

function sample(x, y) {
  if (!insideRoundRect(x, y, 0, 0, SIZE, SIZE, 96)) return null;

  for (let i = 0; i < HEIGHTS.length; i += 1) {
    const left = FIRST_X + i * (BAR_WIDTH + BAR_GAP);
    const top = BASELINE - HEIGHTS[i];
    const radius = BAR_WIDTH / 2;
    // Extend past the baseline so only the top corners round.
    if (y <= BASELINE && insideRoundRect(x, y, left, top, left + BAR_WIDTH, BASELINE + radius, radius)) {
      return FG;
    }
  }
  return BG;
}

function render() {
  const pixels = Buffer.alloc(SIZE * SIZE * 4);
  const step = 1 / SAMPLES;

  for (let py = 0; py < SIZE; py += 1) {
    for (let px = 0; px < SIZE; px += 1) {
      let r = 0;
      let g = 0;
      let b = 0;
      let a = 0;

      for (let sy = 0; sy < SAMPLES; sy += 1) {
        for (let sx = 0; sx < SAMPLES; sx += 1) {
          const hit = sample(px + (sx + 0.5) * step, py + (sy + 0.5) * step);
          if (hit) {
            r += hit[0];
            g += hit[1];
            b += hit[2];
            a += 255;
          }
        }
      }

      const n = SAMPLES * SAMPLES;
      const covered = a / 255;
      const offset = (py * SIZE + px) * 4;
      // Un-premultiply so edge pixels keep the true colour at partial alpha.
      pixels[offset] = covered ? Math.round(r / covered) : 0;
      pixels[offset + 1] = covered ? Math.round(g / covered) : 0;
      pixels[offset + 2] = covered ? Math.round(b / covered) : 0;
      pixels[offset + 3] = Math.round(a / n);
    }
  }
  return pixels;
}

const CRC_TABLE = (() => {
  const table = new Int32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c;
  }
  return table;
})();

function crc32(buf) {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i += 1) c = CRC_TABLE[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, 'latin1'), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([length, body, crc]);
}

function encodePng(pixels) {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(SIZE, 0);
  ihdr.writeUInt32BE(SIZE, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 6; // truecolour with alpha
  ihdr[10] = 0;
  ihdr[11] = 0;
  ihdr[12] = 0;

  const stride = SIZE * 4;
  const raw = Buffer.alloc((stride + 1) * SIZE);
  for (let y = 0; y < SIZE; y += 1) {
    raw[y * (stride + 1)] = 0; // filter: none
    pixels.copy(raw, y * (stride + 1) + 1, y * stride, (y + 1) * stride);
  }

  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr),
    chunk('IDAT', deflateSync(raw, { level: 9 })),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

const out = join(dirname(fileURLToPath(import.meta.url)), '..', 'build', 'icon.png');
mkdirSync(dirname(out), { recursive: true });
writeFileSync(out, encodePng(render()));
console.log(`Wrote ${out} (${SIZE}x${SIZE})`);
