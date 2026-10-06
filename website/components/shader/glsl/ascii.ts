// From the DocBox design file's shader assets (ascii.glsl), unchanged.
const ascii = `/** @resolution */
uniform vec2 u_resolution;

/** @time */
uniform float u_time;

/** @sdf */
uniform sampler2D u_sdf;

/**
 * @label Color
 * @color
 * @default #D6D2FF
 */
uniform vec3 u_color;

/**
 * @label Cell size
 * @default 9
 * @range 4, 24
 */
uniform float u_cell;

/**
 * @label Flicker speed
 * @default 1.5
 * @range 0, 8
 */
uniform float u_flicker;

/**
 * @label Wave speed
 * @default 1
 * @range 0, 4
 */
uniform float u_wave;

float hash(vec2 p) {
  p = fract(p * vec2(123.34, 456.21));
  p += dot(p, p + 45.32);
  return fract(p.x * p.y);
}

void main() {
  vec2 fc = gl_FragCoord.xy;
  vec2 cell = floor(fc / u_cell);
  vec2 cuv = fract(fc / u_cell);
  vec2 center = (cell + 0.5) * u_cell / u_resolution;
  float d = texture2D(u_sdf, center).r;
  float inside = step(0.5, d);

  float tick = floor(u_time * u_flicker + hash(cell) * 17.0);
  vec2 g = floor(vec2(cuv.x * 4.0, cuv.y * 6.0));
  float inGlyph = step(g.x, 2.5) * step(g.y, 4.5);
  float bit = step(0.48, hash(cell * 1.31 + g * 7.77 + tick * 0.173));
  float on = inGlyph * bit;

  float wave = 0.5 + 0.5 * sin(cell.x * 0.22 + cell.y * 0.3 - u_time * u_wave * 1.4);
  float edge = 1.0 - smoothstep(0.0, u_cell * 2.5, d);
  float lum = 0.18 + 0.55 * wave * wave + 0.45 * edge;
  lum *= 0.6 + 0.4 * hash(cell + 3.0);

  float a = clamp(on * inside * lum, 0.0, 1.0);
  gl_FragColor = vec4(u_color * a, a);
}
`;

export default ascii;
