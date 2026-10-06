# DocBox website

The landing page for DocBox: Next.js (App Router) and Tailwind CSS, with Lenis smooth
scrolling, deployed on Vercel. It is pre-rendered and rebuilt at most hourly, so the
GitHub star count stays current.

```sh
bun install
bun run dev      # http://localhost:3000
bun run lint
bun run build    # also type-checks
```

## Layout

- `app/`: the page, layout, global styles and icons.
- `components/`: one file per section (`Hero`, `WorksWith`, `Features`, `Compare`,
  `Closing`), plus the scroll reveal and smooth scrolling.
- `components/shader/`: runs the design's pen.dev shaders on WebGL 2. `glsl/` holds
  them as written in the design file; `ShaderCanvas` supplies the uniforms pen.dev
  does (`@resolution`, `@time`, `@sdf`, `@default`), and `sdf.ts` builds a shape's
  distance field from its SVG path. Offscreen canvases don't draw, visitors who prefer
  reduced motion get a still frame, and each has a static fallback without WebGL.
- `lib/`: links, the star count, the design's shape paths and scroll helpers.

## Logos

`components/marks.tsx` holds the official marks of the engines DocBox works with, each
taken from the project itself: PaddlePaddle's (shown by PaddleOCR beside its name) and
GitHub's via Simple Icons, which sources them from paddlepaddle.org.cn and
github.com/logos; Ollama's from the Ollama repository; MiniCPM's from the MiniCPM-V
repository. They are their owners' trademarks, used to say DocBox works with them.
Tesseract has no official logo, so it appears as its name.

## Deploying

The Vercel project's root directory is `website/`. `vercel --prod` from this folder
deploys it by hand.
