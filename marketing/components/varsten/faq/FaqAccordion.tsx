"use client";

import { useMemo, useState } from "react";

type FaqItem = { question: string; answer: string };

const FAQ_ITEMS: FaqItem[] = [
  {
    question: "What is Varsten?",
    answer:
      "Varsten is AI cost infrastructure for measuring spend, identifying savings opportunities, and applying approved optimizations with traceable results.",
  },
  {
    question: "How does Varsten work?",
    answer:
      "Varsten can ingest usage metadata or sit in the request path through a base URL or SDK integration. Inline integrations can apply enabled optimizations while the dashboard records spend, decisions, and measured savings.",
  },
  {
    question: "How much can Varsten save?",
    answer:
      "Savings depend on model mix, repeated work, prompt size, quality requirements, and which optimizations are safe for the workload. Varsten audits the traffic first rather than promising a universal percentage.",
  },
  {
    question: "Which AI providers does Varsten support?",
    answer: "Varsten supports OpenAI, Anthropic, and Google Gemini. OpenAI is the recommended first controlled rollout; Anthropic and Gemini remain founder-supervised beta paths.",
  },
  {
    question: "How do I integrate Varsten?",
    answer: "Choose metadata-only ingestion for observation without inline risk, a base URL change for evaluation, or a Varsten SDK wrapper for production routes that require direct provider fallback. An in-VPC sidecar is planned but is not currently available.",
  },
  {
    question: "How long does integration take?",
    answer: "A narrow evaluation can begin quickly, but production timing depends on provider setup, fallback testing, security review, and the workload features you use.",
  },
  {
    question: "Is Varsten an AI gateway?",
    answer:
      "Varsten can function as an AI gateway, but its primary purpose is intelligently optimizing AI requests to reduce cost while maintaining quality.",
  },
  {
    question: "What optimizations does Varsten perform?",
    answer:
      "Varsten supports routing, exact and semantic caching, token trimming, compression, downshift, and eligible asynchronous batching. Only enabled and eligible mechanisms should be applied to a workload.",
  },
  {
    question: "Does Varsten reduce response quality?",
    answer: "Any optimization can introduce risk, so Varsten uses configurable quality and latency guardrails, evidence, and rollback controls. Teams should validate each workload and approve the mechanisms appropriate to it.",
  },
  {
    question: "Can I see what Varsten changed?",
    answer: "Yes. Varsten provides visibility into the optimizations it applied, why they were chosen, and the savings they generated.",
  },
  {
    question: "Can I control which optimizations are enabled?",
    answer: "Yes. Individual optimizations can be configured, tuned, or disabled to match your application's requirements.",
  },
  {
    question: "Does Varsten store my prompts?",
    answer:
      "The savings ledger is metadata-oriented and does not use prompt or completion text as its default record. Inline requests still process content in transit, and content-backed features such as semantic caching require explicit storage and retention decisions.",
  },
  {
    question: "Is Varsten secure?",
    answer: "Varsten uses scoped credentials, tenant boundaries, metadata-first records, and explicit fallback paths. It is not yet SOC 2 certified, and teams with formal requirements should review the current security documentation before production use.",
  },
  {
    question: "Can Varsten run in our own infrastructure?",
    answer: "Not currently. The hosted service and SDK integrations are available today. An in-VPC sidecar is planned, so teams that require customer-hosted processing should contact Varsten before evaluating.",
  },
  {
    question: "Does Varsten support streaming responses?",
    answer: "Yes. Varsten fully supports streaming AI responses.",
  },
  {
    question: "Who is Varsten built for?",
    answer: "Varsten is built for startups and enterprises that want to reduce AI infrastructure costs without changing how they build AI applications.",
  },
  {
    question: "How is Varsten different from LiteLLM?",
    answer: "LiteLLM standardizes access to AI providers. Varsten intelligently optimizes AI requests to reduce cost, and can work alongside gateways like LiteLLM.",
  },
  {
    question: "Can Varsten work with LiteLLM?",
    answer: "Varsten may be evaluated alongside an existing gateway through metadata ingestion or a compatible inline path, but the planned Varsten sidecar is not currently available. Compatibility should be validated against the exact request path.",
  },
  {
    question: "How do I know Varsten is working?",
    answer: "The dashboard separates actual spend, baseline cost, savings by mechanism, and data-confidence signals. Estimates remain distinct from verified savings.",
  },
  {
    question: "Why should I use Varsten?",
    answer: "Varsten gives engineering and finance one place to identify AI cost drivers, approve appropriate savings mechanisms, and review the evidence behind the result.",
  },
  {
    question: "What is Varsten's goal?",
    answer: "Varsten's goal is to make production AI costs understandable and controllable without hiding the mechanism, evidence, or operational risk behind the result.",
  },
];

function SearchIcon() {
  return (
    <svg
      aria-hidden="true"
      className="h-4 w-4"
      fill="none"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.8"
      viewBox="0 0 24 24"
    >
      <circle cx="11" cy="11" r="7" />
      <path d="m21 21-4.3-4.3" />
    </svg>
  );
}

function FaqRow({ isOpen, item, onToggle }: { isOpen: boolean; item: FaqItem; onToggle: () => void }) {
  return (
    <div className="border-b border-border last:border-b-0">
      <button
        type="button"
        aria-expanded={isOpen}
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-6 px-6 py-6 text-left transition-colors hover:bg-muted/60 sm:px-8"
      >
        <span className="text-[16px] font-medium text-ink sm:text-[18px]">{item.question}</span>
        <span
          aria-hidden="true"
          className={`flex h-7 w-7 shrink-0 items-center justify-center border border-border text-[16px] leading-none text-ink-soft transition-transform duration-150 ${
            isOpen ? "rotate-45" : ""
          }`}
        >
          +
        </span>
      </button>
      {isOpen ? (
        <div className="px-6 pb-6 sm:px-8">
          <p className="max-w-3xl text-[14px] leading-[1.7] text-ink-soft">{item.answer}</p>
        </div>
      ) : null}
    </div>
  );
}

export function FaqAccordion() {
  const [query, setQuery] = useState("");
  const [openIndex, setOpenIndex] = useState<number | null>(null);

  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return FAQ_ITEMS;
    return FAQ_ITEMS.filter(
      (item) => item.question.toLowerCase().includes(normalized) || item.answer.toLowerCase().includes(normalized),
    );
  }, [query]);

  return (
    <>
      <div className="relative mb-6">
        <span className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-ink-soft">
          <SearchIcon />
        </span>
        <input
          type="search"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setOpenIndex(null);
          }}
          placeholder="Search questions"
          aria-label="Search FAQ"
          className="h-12 w-full border border-border bg-background pl-11 pr-4 text-[14px] outline-none transition-colors focus:border-ink"
        />
      </div>

      <div className="border border-border">
        {filtered.length ? (
          filtered.map((item) => {
            const index = FAQ_ITEMS.indexOf(item);
            return (
              <FaqRow
                key={item.question}
                item={item}
                isOpen={openIndex === index}
                onToggle={() => setOpenIndex((current) => (current === index ? null : index))}
              />
            );
          })
        ) : (
          <div className="px-6 py-16 text-center text-[14px] text-ink-soft sm:px-8">
            No questions match &ldquo;{query}&rdquo;.
          </div>
        )}
      </div>
    </>
  );
}
