import type { Metadata } from "next";
import { ContentPage, ContentSection } from "../content-page";

export const metadata: Metadata = {
  title: "Changelog — Varsten",
  description: "Product updates and release notes for Varsten.",
};

export default function ChangelogPage() {
  return (
    <ContentPage
      eyebrow="Changelog"
      title="Product Updates"
      description="Release notes and product updates will live here."
    >
      <ContentSection title="Latest updates">
        <p>No public changelog entries have been published yet.</p>
      </ContentSection>
    </ContentPage>
  );
}
