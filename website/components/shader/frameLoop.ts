// One requestAnimationFrame loop for every shader on the page. Canvases join while they
// are on screen and leave when they scroll away, so offscreen effects cost nothing, and
// all of them share one clock so their motion stays in step.

type Draw = (seconds: number) => void;

const draws = new Set<Draw>();
let frame = 0;
const origin = typeof performance === "undefined" ? 0 : performance.now();

export const now = () => (performance.now() - origin) / 1000;

function tick() {
  const t = now();
  for (const draw of draws) draw(t);
  frame = draws.size ? requestAnimationFrame(tick) : 0;
}

export function join(draw: Draw) {
  draws.add(draw);
  if (!frame) frame = requestAnimationFrame(tick);
}

export function leave(draw: Draw) {
  draws.delete(draw);
}
