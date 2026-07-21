import Image from "next/image";
import { AI_COST_REPORT_HREF, CONTACT_HREF } from "@/app/site-links";
import { SystemStatus } from "./SystemStatus";

export function Footer() {
  const cols = [
    {
      head: "Product",
      links: [
        ["Levers", "/#levers"],
        ["Integrations", "/#integrations"],
        ["Pricing", "/pricing"],
        ["Product", "/product-tour"],
        ["Savings proof", "/proof"],
      ],
    },
    {
      head: "Docs",
      links: [
        ["Quickstart", "/docs/quickstart"],
        ["OpenAI SDK", "/docs/openai-sdk"],
        ["Architecture", "/docs/integration-paths"],
      ],
    },
    {
      head: "Company",
      links: [
        ["Enterprise", "/enterprise"],
        ["About", "/about"],
        ["Contact", CONTACT_HREF],
        ["FAQ", "/faq"],
      ],
    },
    {
      head: "Legal",
      links: [
        ["Security", "/security"],
        ["Terms", "/terms"],
        ["Privacy", "/privacy"],
      ],
    },
  ];

  return (
    <footer className="bg-background">
      <div className="mx-auto max-w-[1400px] px-6 md:px-10">
        <div className="grid gap-x-10 gap-y-12 py-24 md:grid-cols-2 md:py-32 lg:grid-cols-12">
          <div className="md:col-span-2 lg:col-span-4 lg:pr-8">
            <div className="flex items-center">
              <Image
                src="/varsten-logo.svg"
                alt="Varsten"
                width={445}
                height={88}
                className="h-4 w-auto"
              />
            </div>
            <div className="mt-8 max-w-sm border-t border-border pt-6">
              <div className="mono text-[10px] uppercase tracking-[0.28em] text-ink-soft">
                The AI Cost Report
              </div>
              <p className="mt-3 text-[13px] leading-6 text-ink-soft">
                Weekly updates on AI pricing and cost optimization.
              </p>
              <form
                action={AI_COST_REPORT_HREF}
                method="get"
                target="_blank"
                className="mt-4 flex max-w-sm flex-col gap-2 sm:flex-row"
              >
                <input
                  type="email"
                  name="email"
                  required
                  placeholder="Email address"
                  aria-label="Email address for The AI Cost Report"
                  className="h-10 min-w-0 flex-1 border border-border bg-background px-3 text-[13px] text-ink outline-none placeholder:text-ink-soft/65 focus:border-ink"
                />
                <input type="hidden" name="r" value="59dimx" />
                <input type="hidden" name="utm_source" value="varsten_footer" />
                <input type="hidden" name="utm_medium" value="site" />
                <input type="hidden" name="utm_campaign" value="footer_signup" />
                <button
                  type="submit"
                  className="inline-flex h-10 shrink-0 items-center justify-center gap-2 bg-ink px-4 text-[13px] font-medium text-primary-foreground transition-opacity hover:opacity-90"
                >
                  Subscribe
                </button>
              </form>
            </div>
          </div>

          <div className="grid gap-x-10 gap-y-12 md:col-span-2 md:grid-cols-2 lg:col-span-8 lg:grid-cols-4 lg:justify-items-end">
            {cols.map((c) => (
              <div key={c.head} className="w-fit">
                <div className="mono mb-5 text-[10px] uppercase tracking-[0.28em] text-ink-soft">
                  {c.head}
                </div>
                <ul className="grid gap-3">
                  {c.links.map(([label, href]) => (
                    <li key={label}>
                      <a
                        href={href}
                        className="text-[13px] text-ink transition-colors hover:text-blueprint"
                      >
                        {label}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>

        <div className="mono flex flex-col items-start justify-between gap-4 border-t border-border py-6 text-[11px] uppercase tracking-[0.24em] text-ink-soft md:flex-row md:items-center">
          <span>© 2026 Varsten Systems, Inc.</span>
          <span>Rev. 07·2026 · Doc 001</span>
          <SystemStatus />
        </div>
      </div>
    </footer>
  );
}
