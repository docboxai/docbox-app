// From the DocBox design file's shader assets (rays.glsl), unchanged.
const rays = `/** @resolution */
uniform vec2 u_resolution;

/** @time */
uniform float u_time;

/**
 * @label Color
 * @color
 * @default #DAD7FF
 */
uniform vec3 u_color;

/**
 * @label Strength
 * @default 0.6
 * @range 0, 1.5
 */
uniform float u_strength;

/**
 * @label Speed
 * @default 0.5
 * @range 0, 3
 */
uniform float u_speed;

float hash(vec2 p) {
  p = fract(p * vec2(123.34, 456.21));
  p += dot(p, p + 45.32);
  return fract(p.x * p.y);
}

float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), f.x), mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), f.x), f.y);
}

void main() {
  vec2 uv = gl_FragCoord.xy / u_resolution;
  float t = u_time * u_speed;

  float rays = noise(vec2(uv.x * 9.0, t * 0.5)) * noise(vec2(uv.x * 23.0 + 4.0, -t * 0.35));
  float fade = pow(1.0 - uv.y, 1.6);
  float sides = smoothstep(0.0, 0.18, uv.x) * smoothstep(1.0, 0.82, uv.x);
  float a = (0.10 + 0.9 * rays) * fade * sides;

  vec2 g = vec2(uv.x * 16.0, uv.y * 12.0 * u_resolution.y / u_resolution.x - t * 0.9);
  vec2 cell = floor(g);
  vec2 f = fract(g) - 0.5;
  float pick = step(0.86, hash(cell));
  vec2 jitter = vec2(hash(cell + 1.7), hash(cell + 9.1)) - 0.5;
  float spark = smoothstep(0.12, 0.0, length(f - jitter * 0.5)) * pick;
  a += spark * (1.0 - uv.y) * sides * 0.9;

  a = clamp(a * u_strength, 0.0, 1.0);
  gl_FragColor = vec4(u_color * a, a);
}
`;

export default rays;
