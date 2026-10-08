// The light terms of the design's glass.glsl: the white lift, the moving sheen, the rim
// and the lens tint, with the same uniforms and math. glass.glsl also blurs and tints the
// content behind it (@backdrop), which a web page can't hand to WebGL; GlassFolder does
// that part with CSS backdrop-filter, and this canvas is added on top (plus-lighter).
const glassHighlights = `/** @resolution */
uniform vec2 u_resolution;

/** @time */
uniform float u_time;

/** @sdf */
uniform sampler2D u_sdf;

/**
 * @label Tint
 * @color
 * @default #9CC2F2
 */
uniform vec3 u_tint;

/**
 * @label Bevel width
 * @default 22
 * @range 2, 60
 */
uniform float u_bevel;

/**
 * @label Sheen
 * @default 0.35
 * @range 0, 1
 */
uniform float u_sheen;

void main() {
  vec2 uv = gl_FragCoord.xy / u_resolution;
  vec4 sd = texture2D(u_sdf, uv);
  float d = sd.r;
  vec2 inward = normalize(sd.gb + vec2(1e-6));

  float edge = 1.0 - clamp(d / max(u_bevel, 1.0), 0.0, 1.0);
  float lens = edge * edge;

  vec3 col = vec3(0.06);

  float band = uv.x * 1.2 + uv.y * 0.9 - fract(u_time * 0.12) * 3.4 + 0.6;
  float sheen = exp(-band * band * 40.0);
  col += vec3(1.0) * sheen * u_sheen * 0.5;

  float rim = smoothstep(2.5, 0.0, d);
  float lightSide = clamp(dot(inward, normalize(vec2(0.5, 1.0))) * 0.5 + 0.5, 0.0, 1.0);
  float lightSide2 = clamp(dot(inward, normalize(vec2(0.5, -1.0))) * 0.5 + 0.5, 0.0, 1.0);
  col += vec3(1.0) * rim * (0.25 + 0.55 * max(lightSide, lightSide2));
  col += u_tint * lens * 0.18;

  float alpha = smoothstep(0.0, 1.0, d);
  col = clamp(col, 0.0, 1.0) * alpha;
  gl_FragColor = vec4(col, max(max(col.r, col.g), col.b));
}
`;

export default glassHighlights;
