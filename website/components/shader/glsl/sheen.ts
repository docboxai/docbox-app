// From the DocBox design file's shader assets (sheen.glsl), unchanged.
const sheen = `/** @resolution */
uniform vec2 u_resolution;

/** @time */
uniform float u_time;

/** @sdf */
uniform sampler2D u_sdf;

/**
 * @label Top color
 * @color
 * @default #8F86FF
 */
uniform vec3 u_top;

/**
 * @label Bottom color
 * @color
 * @default #4318FF
 */
uniform vec3 u_bottom;

/**
 * @label Opacity
 * @default 1
 * @range 0, 1
 */
uniform float u_alpha;

/**
 * @label Sheen
 * @default 0.35
 * @range 0, 1
 */
uniform float u_sheen;

/**
 * @label Sheen speed
 * @default 0.14
 * @range 0, 1
 */
uniform float u_speed;

/**
 * @label Sheen offset
 * @default 0
 * @range 0, 1
 */
uniform float u_offset;

float hash(vec2 p) {
  p = fract(p * vec2(123.34, 456.21));
  p += dot(p, p + 45.32);
  return fract(p.x * p.y);
}

void main() {
  vec2 uv = gl_FragCoord.xy / u_resolution;
  vec4 sd = texture2D(u_sdf, uv);
  float d = sd.r;
  vec2 inward = normalize(sd.gb + vec2(1e-6));

  vec3 col = mix(u_bottom, u_top, smoothstep(0.0, 1.0, uv.y));

  float ph = fract(u_time * u_speed + u_offset);
  float band = uv.x * 1.1 - uv.y * 0.7 - ph * 3.6 + 1.2;
  float sheen = exp(-band * band * 30.0);
  col += vec3(1.0) * sheen * u_sheen * 0.45;

  float breathe = 0.5 + 0.5 * sin(u_time * 0.9 + u_offset * 6.2832);
  col += u_top * 0.06 * breathe;

  float rim = smoothstep(2.0, 0.0, d);
  float topLit = clamp(-inward.y * 0.5 + 0.5, 0.0, 1.0);
  col += vec3(1.0) * rim * (0.12 + 0.4 * topLit);

  col += (hash(gl_FragCoord.xy) - 0.5) * 0.015;
  float a = smoothstep(0.0, 1.0, d) * u_alpha;
  gl_FragColor = vec4(clamp(col, 0.0, 1.0) * a, a);
}
`;

export default sheen;
