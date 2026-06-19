import { VarstenLogo } from "@/components/varsten-logo"

const columns = [
  {
    heading: "Product",
    links: [
      { label: "Overview", href: "#product" },
      { label: "How it works", href: "#how-it-works" },
      { label: "Savings levers", href: "#how-it-works" },
      { label: "Pricing", href: "#pricing" },
      { label: "Security", href: "#security" },
    ],
  },
  {
    heading: "Developers",
    links: [
      { label: "Documentation", href: "https://docs.varsten.ai" },
      { label: "API reference", href: "https://docs.varsten.ai" },
      { label: "Status", href: "mailto:mail@varsten.ai?subject=Varsten%20status%20question" },
      { label: "Changelog", href: "https://docs.varsten.ai" },
    ],
  },
  {
    heading: "Company",
    links: [
      { label: "Log in", href: "https://app.varsten.ai" },
      { label: "Book setup call", href: "mailto:mail@varsten.ai?subject=Varsten%20setup%20call" },
      { label: "Privacy", href: "mailto:mail@varsten.ai?subject=Varsten%20privacy" },
      { label: "DPA", href: "mailto:mail@varsten.ai?subject=DPA%20request" },
    ],
  },
]

export function SiteFooter() {
  return (
    <footer className="border-t border-border bg-card">
      <div className="mx-auto max-w-7xl px-4 py-14 sm:px-6 lg:px-8">
        <div className="grid gap-10 lg:grid-cols-[1.5fr_1fr_1fr_1fr]">
          <div>
            <VarstenLogo />
            <p className="mt-4 max-w-xs text-sm leading-relaxed text-muted-foreground">
              The financial control plane for AI spend. Optimize automatically,
              keep quality safe, and prove the savings.
            </p>
          </div>

          {columns.map((col) => (
            <div key={col.heading}>
              <h3 className="text-sm font-semibold text-foreground">
                {col.heading}
              </h3>
              <ul className="mt-4 space-y-2.5">
                {col.links.map((link) => (
                  <li key={link.label}>
                    <a
                      href={link.href}
                      className="text-sm text-muted-foreground transition-colors hover:text-foreground"
                    >
                      {link.label}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-12 flex flex-col items-center justify-between gap-4 border-t border-border pt-6 sm:flex-row">
          <p className="text-xs text-muted-foreground">
            © {new Date().getFullYear()} Varsten, Inc. All rights reserved.
          </p>
          <p className="text-xs text-muted-foreground">
            Not affiliated with OpenAI, Anthropic, or Google. Compatible proxy
            interfaces only.
          </p>
        </div>
      </div>
    </footer>
  )
}
