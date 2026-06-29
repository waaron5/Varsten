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
      title="How Varsten handles your data"
      description="Last updated June 13, 2026. This page explains the data Varsten expects to handle across the website, the app, and the proxy."
    >
      <ContentSection title="Information we collect">
        <p>
          Varsten may collect contact details you submit, account information needed to run the service, usage and
          billing data, support messages, and technical details such as your IP address, browser, device, and request
          logs.
        </p>
      </ContentSection>

      <ContentSection title="AI proxy data">
        <p>
          When you route requests through Varsten, the service may process prompts, responses, model names, timing,
          routing decisions, cache decisions, eval results, and cost attribution data. Your route settings control
          retention, reuse, and optimization for each workload.
        </p>
      </ContentSection>

      <ContentSection title="How we use information">
        <ul className="lp-content-list">
          <li>Run, secure, debug, and improve the Varsten service.</li>
          <li>Measure AI spend, response reuse, routing quality, and confirmed savings.</li>
          <li>Answer sales, support, security, and legal requests.</li>
          <li>Send service notices and product updates where allowed.</li>
          <li>Meet legal, billing, and fraud-prevention duties.</li>
        </ul>
      </ContentSection>

      <ContentSection title="Sharing and subprocessors">
        <p>
          Varsten may share information with infrastructure, analytics, communications, payment, security, and model
          provider subprocessors when needed to run the service. Varsten does not sell personal information.
        </p>
      </ContentSection>

      <ContentSection title="Retention and choices">
        <p>
          Varsten keeps information for as long as it needs to run the service, meet legal duties, settle disputes, and
          keep audit records. You can ask to access, correct, delete, or export your information where the law allows by
          contacting Varsten.
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
