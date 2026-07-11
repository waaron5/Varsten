"use client";

import { useMemo, useState } from "react";

type FaqItem = { question: string; answer: string };

const FAQ_ITEMS: FaqItem[] = [
  {
    question: "What is Varsten?",
    answer:
      "Varsten is an AI infrastructure platform that automatically reduces LLM costs by intelligently optimizing every AI request.",
  },
  {
    question: "How does Varsten work?",
    answer:
      "Varsten sits between your application and your AI providers, analyzes every request, applies intelligent optimizations, and forwards the optimized request to the provider.",
  },
  {
    question: "How much can Varsten save?",
    answer:
      "Savings depend on your workload, but organizations typically see savings between 5% and 20%+, with some workloads achieving even greater reductions.",
  },
  {
    question: "Which AI providers does Varsten support?",
    answer: "Varsten currently supports OpenAI, Anthropic, and Google Gemini, with additional providers being added over time.",
  },
  {
    question: "How do I integrate Varsten?",
    answer: "Most teams integrate by changing a single base URL. Varsten also supports an SDK integration and sidecar deployments.",
  },
  {
    question: "How long does integration take?",
    answer: "Most teams can begin routing requests through Varsten in just a few minutes.",
  },
  {
    question: "Is Varsten an AI gateway?",
    answer:
      "Varsten can function as an AI gateway, but its primary purpose is intelligently optimizing AI requests to reduce cost while maintaining quality.",
  },
  {
    question: "What optimizations does Varsten perform?",
    answer:
      "Varsten automatically performs model routing, exact caching, semantic caching, prompt trimming, prompt compression, and other intelligent optimizations when they provide measurable value.",
  },
  {
    question: "Does Varsten reduce response quality?",
    answer: "No. Varsten applies optimizations while respecting configurable quality guardrails, only using optimizations that meet your quality requirements.",
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
      "No by default. Prompt storage is opt-in. Varsten stores the metadata needed to optimize and measure requests, while organizations control whether prompts and responses are retained.",
  },
  {
    question: "Is Varsten secure?",
    answer: "Yes. Varsten is designed to securely proxy AI requests and supports deployment options that allow organizations to keep AI traffic within their own infrastructure.",
  },
  {
    question: "Can Varsten run in our own infrastructure?",
    answer: "Yes. Varsten supports multiple deployment models, including gateway and sidecar deployments.",
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
    answer: "Yes. Varsten can be deployed alongside LiteLLM as an optimization sidecar.",
  },
  {
    question: "How do I know Varsten is working?",
    answer: "Varsten shows every optimization it applied, the estimated savings from each optimization, and your overall cost reduction.",
  },
  {
    question: "Why should I use Varsten?",
    answer: "Varsten lets you reduce AI costs automatically without changing your application logic or sacrificing output quality.",
  },
  {
    question: "What is Varsten's goal?",
    answer: "Varsten's goal is to make AI dramatically cheaper by automatically applying the smartest optimization strategy to every AI request.",
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
