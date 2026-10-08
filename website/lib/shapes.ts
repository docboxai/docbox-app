// Outlines from the design file, used both to draw the shapes and to give their shaders
// a distance field. Each `rect` is where the path's box sits inside its node, in the
// design's pixels.
import type { SdfShape } from "@/components/shader/sdf";
import { roundedRectPath } from "@/components/shader/sdf";

/** The DocBox mark: the box with two shelves, and its folded corner. */
export const LOGO_BODY =
  "M272.39999 115.49999l-110-109.29999c-4.1-4.2-9.79998-6.2-15.6-6.2l-96.39999 0.4c-28.5 0-50.4 21.9-50.4 50.89999l0 198.40002c0 27.10001 21.1 48.29999 48.6 48.29999l183.19999-0.60001c27 0 47.50003-22.09997 47.50003-47.29998l0-117.60001c0-6.60001-2.30005-12.49999-6.90003-17.00001z m-108.5 135.70002l-106.59999 0c-8.10001 0-13.9-6.19998-13.9-13.69998 0-7.90002 6.60001-13.70001 13.9-13.70001l106.59999 0c8 0 13.70002 6.20001 13.70002 13.70001 0 7.89996-6.70002 13.69998-13.70002 13.69998z m57.9-51.80002l-164.49999 0c-8.10001 0-13.9-6.09997-13.9-14.1 0-8.19998 6.60001-14 13.9-14l164.49999 0c8.20001 0 13.80002 6.20001 13.80002 14 0 8.00003-6.50003 14.1-13.80002 14.1z";
export const LOGO_CORNER =
  "M70.45688 79.89999l-68.4-68.69999c-4.09999-4.1-1.79999-11.2 4.50002-11.2l52.00002 0c12.99997 0 22.60001 10.2 22.6 22.7l0 52.69999c0 6-6.30002 8.3-10.70004 4.5z";

/** The hero emblem (330 x 346): the mark drawn large, filled by the ASCII shader. */
export const EMBLEM_SIZE = [330, 346] as const;
export const EMBLEM: readonly SdfShape[] = [
  { d: LOGO_BODY, viewBox: [0, 0, 279.3, 298], rect: [0, 0, 321.195, 342.7] },
  { d: LOGO_CORNER, viewBox: [0, 0, 81.157, 81.756], rect: [214.065, 0.46, 93.33, 94.019] },
];

/** Front of the glass folder in "One folder in" (320 x 170). */
export const GLASS_FRONT_PATH =
  "M18.46154 0l96 0c17.23077 0 22.15385 25.5 43.07693 25.5l144.00001 0q18.46152 0 17.23078 14.16666l-9.84616 117.11111q-1.23078 13.22223-18.46155 13.22223l-260.92309 0q-17.23077 0-18.46154-13.22223l-9.84615-142.6111q-1.23077-14.16667 17.23077-14.16667z";
export const GLASS_FRONT: readonly SdfShape[] = [
  { d: GLASS_FRONT_PATH, viewBox: [0, 0, 320, 170], rect: [0, 0, 320, 170] },
];

/** Back of the folder in "Batches that stay organised" (210 x 206). */
export const BATCH_FOLDER_BACK = "M0 24q0-24 24-24h62c18 0 22 22 42 22h88q24 0 24 24v160q0 24-24 24h-192q-24 0-24-24z";

/** Front of that folder (210 x 104, radii 4 4 22 22). */
export const BATCH_FOLDER_FRONT_PATH = roundedRectPath(210, 104, [4, 4, 22, 22]);
export const BATCH_FOLDER_FRONT: readonly SdfShape[] = [
  { d: BATCH_FOLDER_FRONT_PATH, viewBox: [0, 0, 210, 104], rect: [0, 0, 210, 104] },
];

/** The two folder layers in "Every read, kept on your disk" (206 x 206, drawn in 240 x 240). */
export const KEEP_LAYER_MID_PATH = "M0 150c40 0 58-32 104-32h42c28 0 32-34 60-34h34v156h-240z";
export const KEEP_LAYER_FRONT_PATH = "M0 150q0-22 22-22h48c30 0 35 32 70 32h78q22 0 22 22v58h-240z";
export const KEEP_LAYER_MID: readonly SdfShape[] = [
  { d: KEEP_LAYER_MID_PATH, viewBox: [0, 0, 240, 240], rect: [0, 0, 206, 206] },
];
export const KEEP_LAYER_FRONT: readonly SdfShape[] = [
  { d: KEEP_LAYER_FRONT_PATH, viewBox: [0, 0, 240, 240], rect: [0, 0, 206, 206] },
];
