// Builds the signed distance field pen.dev hands a shader as its @sdf uniform: the
// distance from each pixel to the node's outline, in pixels, positive inside, with its
// gradient (the direction of increasing distance) in the next two channels.

export interface SdfShape {
  /** SVG path data, as in the design file. */
  d: string;
  /** The path's own coordinate box: [x, y, width, height]. */
  viewBox: readonly [number, number, number, number];
  /** Where that box sits in the canvas, in CSS pixels: [x, y, width, height]. */
  rect: readonly [number, number, number, number];
}

const INF = 1e20;

// Felzenszwalb & Huttenlocher's 1-D squared distance transform (exact, linear time).
function edt1d(f: Float64Array, n: number, out: Float64Array, v: Int32Array, z: Float64Array) {
  let k = 0;
  v[0] = 0;
  z[0] = -INF;
  z[1] = INF;
  for (let q = 1; q < n; q++) {
    let s = (f[q] + q * q - (f[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k]);
    while (s <= z[k]) {
      k--;
      s = (f[q] + q * q - (f[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k]);
    }
    k++;
    v[k] = q;
    z[k] = s;
    z[k + 1] = INF;
  }
  k = 0;
  for (let q = 0; q < n; q++) {
    while (z[k + 1] < q) k++;
    out[q] = (q - v[k]) * (q - v[k]) + f[v[k]];
  }
}

// Squared distance from every pixel to the nearest seed pixel.
function edt2d(seed: Uint8Array, w: number, h: number): Float64Array {
  const grid = new Float64Array(w * h);
  for (let i = 0; i < grid.length; i++) grid[i] = seed[i] ? 0 : INF;
  const n = Math.max(w, h);
  const f = new Float64Array(n);
  const out = new Float64Array(n);
  const v = new Int32Array(n);
  const z = new Float64Array(n + 1);
  for (let x = 0; x < w; x++) {
    for (let y = 0; y < h; y++) f[y] = grid[y * w + x];
    edt1d(f, h, out, v, z);
    for (let y = 0; y < h; y++) grid[y * w + x] = out[y];
  }
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) f[x] = grid[y * w + x];
    edt1d(f, w, out, v, z);
    for (let x = 0; x < w; x++) grid[y * w + x] = out[x];
  }
  return grid;
}

/**
 * The union of `shapes` as an RGBA float texture of `width` x `height` texels (one per
 * CSS pixel), bottom row first to match gl_FragCoord: r = signed distance in pixels,
 * g/b = its gradient per texel.
 */
export function buildSdf(shapes: readonly SdfShape[], width: number, height: number): Float32Array {
  const w = Math.max(1, Math.round(width));
  const h = Math.max(1, Math.round(height));
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) throw new Error("2D canvas unavailable");
  ctx.fillStyle = "#fff";
  for (const { d, viewBox: [vx, vy, vw, vh], rect: [rx, ry, rw, rh] } of shapes) {
    const sx = rw / vw;
    const sy = rh / vh;
    ctx.setTransform(sx, 0, 0, sy, rx - vx * sx, ry - vy * sy);
    ctx.fill(new Path2D(d), "nonzero");
  }
  const alpha = ctx.getImageData(0, 0, w, h).data;

  const inside = new Uint8Array(w * h);
  const outside = new Uint8Array(w * h);
  for (let i = 0; i < w * h; i++) {
    inside[i] = alpha[i * 4 + 3] >= 128 ? 1 : 0;
    outside[i] = 1 - inside[i];
  }
  const toInside = edt2d(inside, w, h);
  const toOutside = edt2d(outside, w, h);

  // Signed distance, top row first. Edge pixels use their antialiased coverage, which
  // is a better sub-pixel estimate than the half-pixel step of the binary transform.
  const dist = new Float32Array(w * h);
  for (let i = 0; i < w * h; i++) {
    const a = alpha[i * 4 + 3] / 255;
    if (a > 0 && a < 1) dist[i] = a - 0.5;
    else dist[i] = inside[i] ? Math.sqrt(toOutside[i]) - 0.5 : 0.5 - Math.sqrt(toInside[i]);
  }

  const at = (x: number, yUp: number) => {
    const cx = Math.min(w - 1, Math.max(0, x));
    const cy = Math.min(h - 1, Math.max(0, yUp));
    return dist[(h - 1 - cy) * w + cx];
  };
  const data = new Float32Array(w * h * 4);
  for (let yUp = 0; yUp < h; yUp++) {
    for (let x = 0; x < w; x++) {
      const o = (yUp * w + x) * 4;
      data[o] = at(x, yUp);
      data[o + 1] = (at(x + 1, yUp) - at(x - 1, yUp)) / 2;
      data[o + 2] = (at(x, yUp + 1) - at(x, yUp - 1)) / 2;
      data[o + 3] = 1;
    }
  }
  return data;
}

/** A rounded rectangle as SVG path data, corner radii in the design's order (TL, TR, BR, BL). */
export function roundedRectPath(w: number, h: number, [tl, tr, br, bl]: readonly number[]): string {
  return [
    `M${tl} 0H${w - tr}`,
    `A${tr} ${tr} 0 0 1 ${w} ${tr}V${h - br}`,
    `A${br} ${br} 0 0 1 ${w - br} ${h}H${bl}`,
    `A${bl} ${bl} 0 0 1 0 ${h - bl}V${tl}`,
    `A${tl} ${tl} 0 0 1 ${tl} 0Z`,
  ].join("");
}
