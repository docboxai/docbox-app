// The DocBox mark: a box with two shelves and a folded corner (design/docboxapp.pen,
// "Logo/Mark"). It takes the current text colour, so each placement picks its own.
export function LogoMark({ height = 20, className }: { height?: number; className?: string }) {
  return (
    <svg
      viewBox="0 0 279.3 298"
      height={height}
      width={(height * 279.3) / 298}
      aria-hidden="true"
      className={className}
      fill="currentColor"
    >
      <path d="M272.39999 115.49999l-110-109.29999c-4.1-4.2-9.79998-6.2-15.6-6.2l-96.39999 0.4c-28.5 0-50.4 21.9-50.4 50.89999l0 198.40002c0 27.10001 21.1 48.29999 48.6 48.29999l183.19999-0.60001c27 0 47.50003-22.09997 47.50003-47.29998l0-117.60001c0-6.60001-2.30005-12.49999-6.90003-17.00001z m-108.5 135.70002l-106.59999 0c-8.10001 0-13.9-6.19998-13.9-13.69998 0-7.90002 6.60001-13.70001 13.9-13.70001l106.59999 0c8 0 13.70002 6.20001 13.70002 13.70001 0 7.89996-6.70002 13.69998-13.70002 13.69998z m57.9-51.80002l-164.49999 0c-8.10001 0-13.9-6.09997-13.9-14.1 0-8.19998 6.60001-14 13.9-14l164.49999 0c8.20001 0 13.80002 6.20001 13.80002 14 0 8.00003-6.50003 14.1-13.80002 14.1z" />
      <path
        transform="translate(186.14 0.4)"
        d="M70.45688 79.89999l-68.4-68.69999c-4.09999-4.1-1.79999-11.2 4.50002-11.2l52.00002 0c12.99997 0 22.60001 10.2 22.6 22.7l0 52.69999c0 6-6.30002 8.3-10.70004 4.5z"
      />
    </svg>
  );
}

// The 36px app tile from the top bar: the mark in hero purple on an ink square.
export function LogoTile({ size = 36 }: { size?: number }) {
  return (
    <span
      aria-hidden="true"
      className="flex shrink-0 items-center justify-center rounded-xl bg-ink text-hero"
      style={{ width: size, height: size }}
    >
      <LogoMark height={Math.round(size * 0.56)} />
    </span>
  );
}
