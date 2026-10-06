import { Closing, SiteFooter } from "@/components/Closing";
import { Compare } from "@/components/Compare";
import { Features } from "@/components/Features";
import { Hero } from "@/components/Hero";
import { WorksWith } from "@/components/WorksWith";
import { getStarCount } from "@/lib/github";

// Rebuilt at most hourly, to keep the GitHub star count current.
export const revalidate = 3600;

export default async function Home() {
  const stars = await getStarCount();
  return (
    <>
      <main>
        <Hero />
        <WorksWith />
        <Features />
        <Compare />
        <Closing stars={stars} />
      </main>
      <SiteFooter />
    </>
  );
}
