import {
  ArrowDownRight,
  ArrowUpRight,
  BadgeCheck,
  CircleDot,
  Gauge,
  ShieldCheck,
  Sparkles,
} from "lucide-react"
import { VarstenLogo } from "@/components/varsten-logo"

const sparkline = [38, 41, 39, 46, 44, 52, 49, 58, 55, 61]

function Stat({
  label,
  value,
  sub,
  trend,
  trendDir = "down",
  accent = false,
}: {
  label: string
  value: string
  sub?: string
  trend?: string
  trendDir?: "up" | "down"
  accent?: boolean
}) {
  const TrendIcon = trendDir === "down" ? ArrowDownRight : ArrowUpRight
  return (
    <div className="flex flex-col justify-between rounded-lg border border-border bg-background p-4">
      <p className="text-[0.7rem] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <div className="mt-2 flex items-end justify-between gap-2">
        <span
          className={`text-2xl font-semibold tracking-tight ${accent ? "text-accent" : "text-foreground"}`}
        >
          {value}
        </span>
        {trend && (
          <span className="inline-flex items-center gap-0.5 text-xs font-medium text-accent">
            <TrendIcon className="h-3.5 w-3.5" />
            {trend}
          </span>
        )}
      </div>
      {sub && <p className="mt-1 text-xs text-muted-foreground">{sub}</p>}
    </div>
  )
}

export function CommandCenter() {
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card shadow-2xl shadow-foreground/10 ring-1 ring-foreground/5">
      {/* window chrome */}
      <div className="flex items-center justify-between border-b border-border bg-secondary/60 px-4 py-3">
        <div className="flex items-center gap-3">
          <VarstenLogo className="[&_span:last-child]:text-sm" />
          <span className="hidden text-xs text-muted-foreground sm:inline">
            / Command Center
          </span>
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-background px-2 py-1">
            <span className="h-1.5 w-1.5 rounded-full bg-accent" />
            Live
          </span>
          <span className="hidden rounded-full border border-border bg-background px-2 py-1 sm:inline">
            Nov 2026
          </span>
        </div>
      </div>

      <div className="p-4 sm:p-5">
        {/* top metric grid */}
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat
            label="AI spend this month"
            value="$25,000"
            sub="48.2K requests"
          />
          <Stat
            label="Savings captured"
            value="$5,000"
            trend="20%"
            sub="vs. unoptimized"
            accent
          />
          <Stat
            label="Net savings after fee"
            value="$3,750"
            sub="Varsten fee $1,250"
          />
          <Stat
            label="Annualized net"
            value="$45,000"
            trend="proj."
            sub="finance-verified"
            accent
          />
        </div>

        {/* lower row */}
        <div className="mt-3 grid gap-3 lg:grid-cols-3">
          {/* savings ledger / chart */}
          <div className="rounded-lg border border-border bg-background p-4 lg:col-span-2">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-semibold text-foreground">
                  Verified savings ledger
                </p>
                <p className="text-xs text-muted-foreground">
                  Attributed by lever, route &amp; method
                </p>
              </div>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-accent/10 px-2.5 py-1 text-xs font-medium text-accent">
                <BadgeCheck className="h-3.5 w-3.5" />
                Reconciled
              </span>
            </div>

            {/* bar chart */}
            <div className="mt-4 flex h-24 items-end gap-1.5">
              {sparkline.map((v, i) => (
                <div
                  key={i}
                  className="flex-1 rounded-t-sm bg-accent/80"
                  style={{ height: `${v}%` }}
                  aria-hidden="true"
                />
              ))}
            </div>

            <div className="mt-4 space-y-2.5 border-t border-border pt-3">
              {[
                { lever: "Prompt + response cache", amount: "$2,140", pct: "43%" },
                { lever: "Safe model routing", amount: "$1,610", pct: "32%" },
                { lever: "Context trimming", amount: "$830", pct: "17%" },
                { lever: "Request batching", amount: "$420", pct: "8%" },
              ].map((row) => (
                <div
                  key={row.lever}
                  className="flex items-center justify-between text-sm"
                >
                  <span className="flex items-center gap-2 text-muted-foreground">
                    <CircleDot className="h-3.5 w-3.5 text-accent" />
                    {row.lever}
                  </span>
                  <span className="flex items-center gap-3">
                    <span className="text-xs text-muted-foreground">
                      {row.pct}
                    </span>
                    <span className="font-medium text-foreground">
                      {row.amount}
                    </span>
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* right column: quality + ops */}
          <div className="flex flex-col gap-3">
            <div className="rounded-lg border border-border bg-background p-4">
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-2 text-sm font-medium text-foreground">
                  <Gauge className="h-4 w-4 text-accent" />
                  Quality held
                </span>
                <span className="text-lg font-semibold text-foreground">
                  94.2
                </span>
              </div>
              <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-secondary">
                <div className="h-full w-[94%] rounded-full bg-accent" />
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                Guardrail floor 92.0 · no regression
              </p>
            </div>

            <div className="rounded-lg border border-border bg-background p-4">
              <p className="flex items-center gap-2 text-sm font-medium text-foreground">
                <Sparkles className="h-4 w-4 text-accent" />
                Cache hit rate
              </p>
              <p className="mt-1 text-2xl font-semibold text-foreground">61%</p>
            </div>

            <div className="rounded-lg border border-border bg-background p-4">
              <p className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">Open opportunities</span>
                <span className="font-semibold text-foreground">3</span>
              </p>
              <p className="mt-2 flex items-center justify-between text-sm">
                <span className="text-muted-foreground">Active optimizations</span>
                <span className="font-semibold text-foreground">11</span>
              </p>
              <p className="mt-3 flex items-center gap-1.5 border-t border-border pt-3 text-xs font-medium text-accent">
                <ShieldCheck className="h-3.5 w-3.5" />
                Fail-open · proofs attached
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
