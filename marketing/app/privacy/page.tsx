import type { Metadata } from "next";
import { CONTACT_EMAIL, ContentCallout, ContentPage, ContentSection } from "../content-page";

export const metadata: Metadata = {
  title: "Privacy — Varsten",
  description: "Varsten privacy practices for website, lead, app, and proxy data.",
};

export default function PrivacyPage() {
  return (
    <ContentPage
      eyebrow="Privacy"
      title="Privacy practices for Varsten."
      description="Last updated June 13, 2026. This page explains the practical data categories Varsten expects to handle across the website, app, and proxy."
    >
      <ContentSection title="Information we collect">
        <p>
          Varsten may collect contact information you submit, account information needed to operate the service, usage
          and billing metadata, support messages, and technical information such as IP address, browser, device, and
          request logs.
        </p>
      </ContentSection>

      <ContentSection title="AI proxy data">
        <p>
          When you route requests through Varsten, the service may process prompts, responses, model names, timing,
          routing decisions, cache decisions, eval results, and cost attribution metadata. Route settings should control
          retention, reuse, and optimization behavior for each workload.
        </p>
      </ContentSection>

      <ContentSection title="How we use information">
        <ul className="lp-content-list">
          <li>Provide, secure, debug, and improve the Varsten service.</li>
          <li>Measure AI spend, response reuse, routing quality, and verified savings.</li>
          <li>Respond to sales, support, security, and legal requests.</li>
          <li>Send service notices and product updates where permitted.</li>
          <li>Comply with legal, billing, and fraud-prevention obligations.</li>
        </ul>
      </ContentSection>

      <ContentSection title="Sharing and subprocessors">
        <p>
          Varsten may share information with infrastructure, analytics, communications, payment, security, and model
          provider subprocessors as needed to operate the service. Varsten does not sell personal information.
        </p>
      </ContentSection>

      <ContentSection title="Retention and choices">
        <p>
          Varsten keeps information for as long as needed to provide the service, meet legal obligations, resolve
          disputes, and maintain audit records. Customers may request access, correction, deletion, or export where
          applicable by contacting Varsten.
        </p>
      </ContentSection>

      <ContentCallout title="Privacy contact">
        <p>
          For privacy requests, email <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
        </p>
      </ContentCallout>
    </ContentPage>
  );
}
