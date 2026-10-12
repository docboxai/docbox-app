import { Closing, SiteFooter } from "@/components/Closing";
import { Compare } from "@/components/Compare";
import { Features } from "@/components/Features";
import { Hero } from "@/components/Hero";
import { SiteHeader } from "@/components/SiteHeader";
import { WorksWith } from "@/components/WorksWith";
import { getInstallers, getStarCount } from "@/lib/github";

// Rebuilt at most hourly, to keep the GitHub star count and the download links current.
export const revalidate = 3600;

export default async function Home() {
  const [stars, installers] = await Promise.all([getStarCount(), getInstallers()]);
  return (
    <>
      <SiteHeader stars={stars} />
      <main>
        <Hero installers={installers} />
        <WorksWith />
        <Features />
        <Compare />
        <Closing stars={stars} />
      </main>
      <SiteFooter />
    </>
  );
}
