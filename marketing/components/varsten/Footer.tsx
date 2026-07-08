import { SystemStatus } from "./SystemStatus";

export function Footer() {
  const cols = [
    {
      head: "Product",
      links: [
        ["Levers", "#levers"],
        ["Integrations", "#integrations"],
        ["Pricing", "#pricing"],
        ["Changelog", "/changelog"],
      ],
    },
    {
      head: "Docs",
      links: [
        ["Quickstart", "/docs#quickstart"],
        ["SDK reference", "/docs#sdk-reference"],
        ["Architecture", "/docs#architecture"],
        ["Security", "/security"],
      ],
    },
    {
      head: "Company",
      links: [
        ["About", "/about"],
        ["Contact", "/contact"],
        ["Terms", "/terms"],
        ["Privacy", "/privacy"],
      ],
    },
  ];

  return (
    <footer className="bg-background">
      <div className="mx-auto max-w-[1400px] px-6 md:px-10">
        <div className="grid gap-12 py-16 md:grid-cols-12 md:py-20">
          <div className="md:col-span-5">
            <div className="flex items-center gap-2">
              <span className="mono text-[11px] uppercase tracking-[0.28em] text-ink-soft">
                V—001
              </span>
              <span className="text-[15px] font-semibold tracking-tight text-ink">
                Varsten
              </span>
            </div>
            <p className="mt-6 max-w-sm text-[14px] leading-[1.6] text-ink-soft">
              A drop-in optimization engine that captures, routes, and reprices
              your LLM traffic in real-time.
            </p>
          </div>

          {cols.map((c) => (
            <div key={c.head} className="md:col-span-2">
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

        <div className="mono flex flex-col items-start justify-between gap-4 border-t border-border py-6 text-[11px] uppercase tracking-[0.24em] text-ink-soft md:flex-row md:items-center">
          <span>© 2026 Varsten Systems, Inc.</span>
          <span>Rev. 07·2026 · Doc 001</span>
          <SystemStatus />
        </div>
      </div>
    </footer>
  );
}
