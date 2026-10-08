// From the DocBox design file's shader assets (aurora.glsl), unchanged.
const aurora = `/** @resolution */
uniform vec2 u_resolution;

/** @time */
uniform float u_time;

/**
 * @label Scroll progress
 * @default 0
 * @range 0, 1
 */
uniform float u_scroll;

/**
 * @label Base
 * @color
 * @default #0B1730
 */
uniform vec3 u_base;

/**
 * @label Glow A
 * @color
 * @default #0E83FF
 */
uniform vec3 u_colA;

/**
 * @label Glow B
 * @color
 * @default #563FFF
 */
uniform vec3 u_colB;

/**
 * @label Intensity
 * @default 0.55
 * @range 0, 1.5
 */
uniform float u_intensity;

/**
 * @label Speed
 * @default 0.35
 * @range 0, 2
 */
uniform float u_speed;

/**
 * @label Dot grid
 * @default 0.5
 * @range 0, 1
 */
uniform float u_grid;

float hash(vec2 p) {
  p = fract(p * vec2(123.34, 456.21));
  p += dot(p, p + 45.32);
  return fract(p.x * p.y);
}

float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  float a = hash(i);
  float b = hash(i + vec2(1.0, 0.0));
  float c = hash(i + vec2(0.0, 1.0));
  float d = hash(i + vec2(1.0, 1.0));
  return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

float fbm(vec2 p) {
  float v = 0.0;
  float a = 0.5;
  for (int i = 0; i < 5; i++) {
    v += a * noise(p);
    p = p * 2.03 + vec2(17.1, 9.2);
    a *= 0.5;
  }
  return v;
}

void main() {
  vec2 p = gl_FragCoord.xy / u_resolution.x;
  float t = u_time * u_speed * 0.2;
  float s = u_scroll;

  vec2 q = p * 1.6 + vec2(0.0, s * 1.4);
  vec2 warp = vec2(fbm(q + vec2(t, -t * 0.6)), fbm(q + vec2(-t * 0.7, t) + 5.2));
  float n1 = fbm(q * 1.2 + warp * 1.6 + vec2(t * 0.5, 0.0));
  float n2 = fbm(q * 0.8 - warp * 1.3 + vec2(3.7, t * 0.4));

  float ribbons = sin((p.x * 2.2 + warp.x * 2.4 + n1 * 1.5 - t * 1.5) * 3.14159);
  ribbons = pow(abs(ribbons), 6.0);

  vec3 col = u_base;
  float mixAB = clamp(n2 * 1.3 - 0.2 + s * 0.5, 0.0, 1.0);
  vec3 glow = mix(u_colA, u_colB, mixAB);
  col += glow * smoothstep(0.35, 0.95, n1) * 0.55 * u_intensity;
  col += glow * ribbons * smoothstep(0.3, 0.8, n2) * 0.22 * u_intensity;

  vec2 g = gl_FragCoord.xy / 28.0;
  vec2 cell = fract(g) - 0.5;
  float dotMask = smoothstep(0.075, 0.035, length(cell));
  float wave = sin(floor(g.y) * 0.35 - floor(g.x) * 0.12 + u_time * u_speed * 1.6 + s * 18.0);
  float tw = smoothstep(0.55, 1.0, wave) * 0.8 + 0.12;
  col += mix(u_colA, vec3(1.0), 0.5) * dotMask * tw * 0.35 * u_grid;

  col += (hash(gl_FragCoord.xy + fract(u_time)) - 0.5) * 0.02;
  gl_FragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}
`;

export default aurora;
