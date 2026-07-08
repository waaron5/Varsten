import type { Metadata } from "next";
import { ContentPage, ContentSection } from "../content-page";

export const metadata: Metadata = {
  title: "About — Varsten",
  description: "About Varsten.",
};

export default function AboutPage() {
  return (
    <ContentPage
      eyebrow="About"
      title="About Varsten"
      description="Varsten helps teams reduce AI spend with measurable, auditable optimization."
    >
      <ContentSection title="What we build">
        <p>
          Varsten is an AI optimization layer for teams that need savings proof, safe rollout controls,
          and provider fallback instead of a black-box proxy.
        </p>
      </ContentSection>
    </ContentPage>
  );
}
