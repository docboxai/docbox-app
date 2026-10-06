"use client";

import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { useReducedMotion } from "@/lib/useReducedMotion";
import { join, leave, now } from "./frameLoop";
import { buildSdf, type SdfShape } from "./sdf";

// Runs one of the design's pen.dev shaders on a canvas. Those shaders are WebGL 1.0
// fragment shaders whose uniforms pen.dev fills in from annotations (@resolution, @time,
// @sdf, @default, ...); this does the same, so the GLSL stays exactly as designed.
//
// pen.dev measures everything in the node's own pixels: a 9 px ASCII cell, a 28 px dot
// grid. To keep that scale on high-density screens while still drawing every device
// pixel, gl_FragCoord is divided by the pixel ratio before the shader's main() runs.

type UniformValue = number | string | readonly number[];

interface UniformInfo {
  name: string;
  type: string;
  role?: "resolution" | "time" | "sdf" | "backdrop" | "mouse";
  fallback?: number[];
}

// Frame drawn when the visitor prefers reduced motion: a still from a few seconds in,
// once each effect has built up.
const STILL_TIME = 3;

const UNIFORM = /(?:\/\*\*((?:(?!\*\/)[\s\S])*)\*\/\s*)?uniform\s+(\w+)\s+(\w+)\s*;/g;

function hexToRgb(hex: string): number[] {
  const n = parseInt(hex.replace("#", "").slice(0, 6), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => c / 255);
}

function toFloats(value: UniformValue): number[] {
  if (typeof value === "number") return [value];
  if (typeof value === "string") return hexToRgb(value);
  return [...value];
}

function parseUniforms(source: string): UniformInfo[] {
  return [...source.matchAll(UNIFORM)].map(([, doc = "", type, name]) => {
    const role = (["resolution", "time", "sdf", "backdrop", "mouse"] as const).find((r) =>
      new RegExp(`@${r}\\b`).test(doc),
    );
    const def = /@default\s+(\S+)/.exec(doc)?.[1];
    const fallback = def === undefined ? undefined : def.startsWith("#") ? hexToRgb(def) : [Number(def)];
    return { name, type, role, fallback };
  });
}

function prepare(source: string): string {
  const body = source
    .replace(/\bgl_FragCoord\b/g, "pd_FragCoord")
    .replace(/\bvoid\s+main\s*\(/, "void pd_main(");
  return [
    "precision highp float;",
    "uniform float pd_pixelRatio;",
    "vec4 pd_FragCoord;",
    body,
    "void main() {",
    "  pd_FragCoord = vec4(gl_FragCoord.xy / pd_pixelRatio, gl_FragCoord.zw);",
    "  pd_main();",
    "}",
  ].join("\n");
}

const VERTEX = "attribute vec2 a_pos;\nvoid main() { gl_Position = vec4(a_pos, 0.0, 1.0); }";

function compile(gl: WebGL2RenderingContext, type: number, src: string): WebGLShader {
  const shader = gl.createShader(type);
  if (!shader) throw new Error("createShader failed");
  gl.shaderSource(shader, src);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    throw new Error(gl.getShaderInfoLog(shader) ?? "shader compile failed");
  }
  return shader;
}

export interface ShaderCanvasProps {
  source: string;
  /** Values for the shader's own uniforms; anything left out uses its @default. */
  uniforms?: Record<string, UniformValue>;
  /** The node's outline for an @sdf uniform. Its rects are in the canvas's CSS pixels,
   * or in `sdfSize` units when given, scaled to the canvas's actual size. */
  sdf?: readonly SdfShape[];
  /** The design size of the node the `sdf` rects are measured in. */
  sdfSize?: readonly [number, number];
  /** Uniforms read on every frame, such as scroll progress. */
  live?: () => Record<string, number>;
  /** Upper bound on device pixels per CSS pixel, for large soft effects. */
  maxPixelRatio?: number;
  className?: string;
  style?: CSSProperties;
  /** Shown until the shader draws, and in its place where WebGL isn't available. */
  fallback?: ReactNode;
}

export function ShaderCanvas({
  source,
  uniforms,
  sdf,
  sdfSize,
  live,
  maxPixelRatio = 2,
  className,
  style,
  fallback,
}: ShaderCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const uniformsRef = useRef(uniforms);
  const liveRef = useRef(live);
  const [ready, setReady] = useState(false);
  const reduced = useReducedMotion();

  useEffect(() => {
    uniformsRef.current = uniforms;
    liveRef.current = live;
  }, [uniforms, live]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const gl = canvas.getContext("webgl2", {
      alpha: true,
      premultipliedAlpha: true,
      antialias: false,
      powerPreference: "low-power",
    });
    if (!gl) return;

    let program: WebGLProgram;
    try {
      program = gl.createProgram();
      gl.attachShader(program, compile(gl, gl.VERTEX_SHADER, VERTEX));
      gl.attachShader(program, compile(gl, gl.FRAGMENT_SHADER, prepare(source)));
      gl.linkProgram(program);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
        throw new Error(gl.getProgramInfoLog(program) ?? "program link failed");
      }
    } catch (err) {
      console.error("DocBox shader failed to build:", err);
      return;
    }
    gl.useProgram(program);

    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const pos = gl.getAttribLocation(program, "a_pos");
    gl.enableVertexAttribArray(pos);
    gl.vertexAttribPointer(pos, 2, gl.FLOAT, false, 0, 0);

    const info = parseUniforms(source);
    const loc = (name: string) => gl.getUniformLocation(program, name);
    const pixelRatioLoc = loc("pd_pixelRatio");

    // Samplers: the outline's distance field, and an empty backdrop (see glassHighlights).
    let unit = 0;
    const textures: WebGLTexture[] = [];
    const sdfInfo = info.find((u) => u.role === "sdf");
    let sdfTexture: WebGLTexture | null = null;
    for (const u of info.filter((u) => u.type === "sampler2D")) {
      const texture = gl.createTexture();
      textures.push(texture);
      gl.activeTexture(gl.TEXTURE0 + unit);
      gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      if (u === sdfInfo) sdfTexture = texture;
      else gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array(4));
      gl.uniform1i(loc(u.name), unit++);
    }

    const setUniform = (u: UniformInfo, values: number[]) => {
      const l = loc(u.name);
      if (!l) return;
      if (u.type === "float") gl.uniform1f(l, values[0]);
      else if (u.type === "int") gl.uniform1i(l, values[0]);
      else if (u.type === "vec2") gl.uniform2fv(l, values.slice(0, 2));
      else if (u.type === "vec3") gl.uniform3fv(l, values.slice(0, 3));
      else if (u.type === "vec4") gl.uniform4fv(l, values.length === 3 ? [...values, 1] : values.slice(0, 4));
    };

    let width = 0;
    let height = 0;
    let drawn = false;
    const resize = () => {
      width = canvas.clientWidth;
      height = canvas.clientHeight;
      if (!width || !height) return;
      const ratio = Math.min(window.devicePixelRatio || 1, maxPixelRatio);
      canvas.width = Math.max(1, Math.round(width * ratio));
      canvas.height = Math.max(1, Math.round(height * ratio));
      gl.viewport(0, 0, canvas.width, canvas.height);
      if (sdf && sdfTexture) {
        const kx = sdfSize ? width / sdfSize[0] : 1;
        const ky = sdfSize ? height / sdfSize[1] : 1;
        const shapes = sdf.map((shape) => ({
          ...shape,
          rect: [shape.rect[0] * kx, shape.rect[1] * ky, shape.rect[2] * kx, shape.rect[3] * ky] as const,
        }));
        const data = buildSdf(shapes, width, height);
        gl.bindTexture(gl.TEXTURE_2D, sdfTexture);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA16F, Math.round(width), Math.round(height), 0, gl.RGBA, gl.FLOAT, data);
      }
    };

    const draw = (time: number) => {
      if (!width || !height) return;
      gl.uniform1f(pixelRatioLoc, canvas.width / width);
      const given = uniformsRef.current ?? {};
      const moving = liveRef.current?.() ?? {};
      for (const u of info) {
        if (u.role === "resolution") setUniform(u, [width, height]);
        else if (u.role === "time") setUniform(u, [time]);
        else if (u.type === "sampler2D" || u.role === "mouse") continue;
        else if (u.name in moving) setUniform(u, [moving[u.name]]);
        else if (u.name in given) setUniform(u, toFloats(given[u.name]));
        else if (u.fallback) setUniform(u, u.fallback);
      }
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      if (!drawn) {
        drawn = true;
        setReady(true);
      }
    };

    const drawStill = () => draw(STILL_TIME);
    let visible = false;
    const show = () => (reduced ? drawStill() : join(draw));

    resize();
    // Resizing clears the canvas, so redraw a frame even when it's offscreen.
    const resizeObserver = new ResizeObserver(() => {
      resize();
      draw(reduced ? STILL_TIME : now());
    });
    resizeObserver.observe(canvas);
    const intersection = new IntersectionObserver(
      ([entry]) => {
        visible = entry.isIntersecting;
        if (visible) show();
        else leave(draw);
      },
      { rootMargin: "120px" },
    );
    intersection.observe(canvas);

    const onLost = (event: Event) => {
      event.preventDefault();
      leave(draw);
      setReady(false);
    };
    canvas.addEventListener("webglcontextlost", onLost);

    // Draw a first frame straight away so the effect is in place before it scrolls in.
    const first = requestAnimationFrame(() => draw(reduced ? STILL_TIME : now()));

    return () => {
      cancelAnimationFrame(first);
      leave(draw);
      resizeObserver.disconnect();
      intersection.disconnect();
      canvas.removeEventListener("webglcontextlost", onLost);
      for (const t of textures) gl.deleteTexture(t);
      gl.deleteBuffer(buffer);
      gl.deleteProgram(program);
    };
  }, [source, sdf, sdfSize, maxPixelRatio, reduced]);

  return (
    <>
      {!ready && fallback}
      <canvas
        ref={canvasRef}
        aria-hidden="true"
        className={className}
        style={{ ...style, opacity: ready ? style?.opacity : 0 }}
      />
    </>
  );
}
