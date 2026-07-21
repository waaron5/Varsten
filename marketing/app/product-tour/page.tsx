import type { Metadata } from "next";
import { START_OBSERVE_HREF } from "../site-links";
import { pageMetadata } from "@/lib/seo";
import { PageCta, SecondaryShell } from "@/components/varsten/SecondaryPage";
import { DashboardShowcase } from "@/components/varsten/product-tour/DashboardShowcase";

export const metadata: Metadata = pageMetadata({
  title: "Product — Varsten",
  description: "Explore the Varsten dashboard for AI spend, savings, cost drivers, and data confidence.",
  path: "/product-tour",
});

export default function ProductTourPage() {
  return (
    <SecondaryShell>
      <section className="bg-background">
        <div className="mx-auto w-full max-w-[1400px] px-6 py-16 md:px-10 md:py-20">
          <h1 className="text-[44px] font-semibold leading-none tracking-[-0.02em] text-ink md:text-[72px]">
            Product
          </h1>
        </div>
      </section>

      <DashboardShowcase />

      <PageCta
        title="See where your AI spend is going."
        description="Connect a workload and let the dashboard build your cost baseline. No production changes required."
        href={START_OBSERVE_HREF}
        label="Start a free audit"
        intent="observe"
        hideEyebrow
      />
    </SecondaryShell>
  );
}
