// From the DocBox design file's shader assets (glow.glsl), unchanged.
const glow = `/** @resolution */
uniform vec2 u_resolution;

/** @time */
uniform float u_time;

/**
 * @label Color
 * @color
 * @default #7F76FF
 */
uniform vec3 u_color;

/**
 * @label Strength
 * @default 0.6
 * @range 0, 1.5
 */
uniform float u_strength;

/**
 * @label Pulse speed
 * @default 0.25
 * @range 0, 2
 */
uniform float u_speed;

void main() {
  vec2 uv = gl_FragCoord.xy / u_resolution;
  float r = length(uv - 0.5) * 2.0;
  float core = exp(-r * r * 3.2) * (0.6 + 0.2 * sin(u_time * u_speed * 5.0));
  float ph = fract(u_time * u_speed);
  float ring = exp(-pow((r - ph) * 9.0, 2.0)) * (1.0 - ph) * 0.35;
  float ph2 = fract(u_time * u_speed + 0.5);
  ring += exp(-pow((r - ph2) * 9.0, 2.0)) * (1.0 - ph2) * 0.35;
  float a = clamp((core + ring) * u_strength, 0.0, 1.0) * smoothstep(1.0, 0.8, r);
  gl_FragColor = vec4(u_color * a, a);
}
`;

export default glow;
