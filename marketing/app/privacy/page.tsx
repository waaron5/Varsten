import type { Metadata } from "next";
import { CONTACT_EMAIL } from "../site-links";
import { PolicyDocument, PolicyList, type PolicySection } from "@/components/varsten/PolicyDocument";
import { SecondaryShell } from "@/components/varsten/SecondaryPage";
import { pageMetadata } from "@/lib/seo";

export const metadata: Metadata = pageMetadata({
  title: "Privacy — Varsten",
  description: "How Varsten Systems, Inc. collects, uses, protects, and retains website, account, and service data.",
  path: "/privacy",
});

const emailLink = <a className="text-ink underline underline-offset-4" href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>;

const sections: PolicySection[] = [
  {
    id: "scope",
    title: "Scope and who we are",
    content: <p>This policy describes how Varsten Systems, Inc. handles personal information through varsten.ai, the Varsten application, customer communications, and related services. A signed agreement or data processing addendum controls if it conflicts with this policy.</p>,
  },
  {
    id: "information",
    title: "Information we collect",
    content: <><p>We collect information provided directly by users and information produced when the service operates.</p><PolicyList><li>Account and contact details, including name, work email, company, and authentication identifiers.</li><li>Commercial and support communications, form submissions, and procurement information.</li><li>Service metadata such as provider, model, token counts, timestamps, workload labels, cost, routing decisions, and diagnostic events.</li><li>Website and device information such as page path, referrer, campaign parameters, browser details, IP-derived security signals, and anonymous analytics identifiers.</li><li>Billing records supplied by payment providers. Varsten does not directly store complete payment-card numbers.</li></PolicyList></>,
  },
  {
    id: "ai-data",
    title: "AI requests and credentials",
    content: <><p>The savings ledger is metadata-oriented; prompt and completion text are not its default record. Inline integrations necessarily process request and response content in transit. Content-backed features, including semantic caching or approved replay, may retain content only when configured for that purpose and subject to applicable retention controls.</p><p>Varsten project keys and connected provider credentials are secrets. They are not analytics properties and must not be submitted through forms, URLs, or support messages.</p></>,
  },
  {
    id: "use",
    title: "How we use information",
    content: <PolicyList><li>Provide, secure, troubleshoot, and improve the service.</li><li>Authenticate users, enforce tenant boundaries, and prevent abuse.</li><li>Calculate spend, evaluate optimization opportunities, and produce savings evidence.</li><li>Respond to inquiries, deliver requested communications, and manage commercial relationships.</li><li>Meet legal obligations and enforce agreements.</li></PolicyList>,
  },
  {
    id: "sharing",
    title: "Sharing and subprocessors",
    content: <><p>We share information with infrastructure, authentication, communications, analytics, payment, monitoring, and model-provider services only as needed to operate Varsten. We may also disclose information when required by law, to protect rights or safety, in a corporate transaction, or at a customer’s direction.</p><p>Varsten does not sell personal information or share it for cross-context behavioral advertising.</p></>,
  },
  {
    id: "retention",
    title: "Retention and deletion",
    content: <p>We retain information for the period needed to provide the service, maintain security and financial records, resolve disputes, and meet legal obligations. Retention can vary by data class and contract. Customers with specific requirements should agree on them before sending production traffic. Backup copies may persist for a limited period after deletion.</p>,
  },
  {
    id: "security-transfers",
    title: "Security and international processing",
    content: <p>We use administrative, technical, and organizational measures intended to protect information. No system is completely secure. Varsten and its service providers may process information in the United States and other locations where they operate, subject to applicable contractual and legal safeguards.</p>,
  },
  {
    id: "rights",
    title: "Your choices and rights",
    content: <p>Depending on location, individuals may have rights to access, correct, delete, restrict, object to, or export personal information, and to withdraw consent where consent is the basis for processing. We may need to verify identity and may retain information where legally permitted or required.</p>,
  },
  {
    id: "children",
    title: "Children",
    content: <p>Varsten is a business service and is not directed to children under 13. We do not knowingly collect personal information from children through the service.</p>,
  },
  {
    id: "changes-contact",
    title: "Changes and contact",
    content: <p>We may update this policy as the service and legal requirements change. The date above identifies the current version. For privacy requests or questions, contact {emailLink}.</p>,
  },
];

export default function PrivacyPage() {
  return <SecondaryShell><PolicyDocument title="Privacy" description="How we collect, use, protect, and retain information across the Varsten website and service." updated="July 21, 2026" sections={sections} /></SecondaryShell>;
}
