"use client";

import { useEffect } from "react";

// Marks each [data-reveal] element as shown the first time it scrolls into view; the
// fade and rise are in globals.css, with a per-element --reveal-delay for staggering.
export function RevealObserver() {
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          entry.target.setAttribute("data-shown", "");
          observer.unobserve(entry.target);
        }
      },
      { rootMargin: "0px 0px -10% 0px" },
    );
    for (const el of document.querySelectorAll("[data-reveal]")) observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return null;
}
