// From the DocBox design file's shader assets (beam.glsl), unchanged.
const beam = `/** @resolution */
uniform vec2 u_resolution;

/** @time */
uniform float u_time;

/**
 * @label Color
 * @color
 * @default #563FFF
 */
uniform vec3 u_color;

/**
 * @label Speed
 * @default 0.22
 * @range 0, 2
 */
uniform float u_speed;

/**
 * @label Trail length
 * @default 0.3
 * @range 0.02, 1
 */
uniform float u_trail;

/**
 * @label Strength
 * @default 0.8
 * @range 0, 1
 */
uniform float u_strength;

void main() {
  vec2 uv = gl_FragCoord.xy / u_resolution;
  float pos = 1.15 - fract(u_time * u_speed) * 1.3;
  float line = exp(-pow((uv.y - pos) * u_resolution.y / 1.6, 2.0));
  float t = clamp((uv.y - pos) / u_trail, 0.0, 1.0);
  float trail = (1.0 - t) * (1.0 - t) * step(pos, uv.y) * 0.3;
  float a = clamp((line + trail) * u_strength, 0.0, 1.0);
  gl_FragColor = vec4(mix(u_color, vec3(1.0), line * 0.4) * a, a);
}
`;

export default beam;
