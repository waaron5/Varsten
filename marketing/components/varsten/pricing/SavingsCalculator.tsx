"use client";

import { useMemo, useState } from "react";

type Workload =
  | "support"
  | "batchable"
  | "agentic"
  | "longContext"
  | "routingSafe"
  | "generalChat";

type Rates = {
  conservative: number;
  realistic: number;
  optimistic: number;
};

const workloadOrder: Workload[] = [
  "support",
  "batchable",
  "agentic",
  "longContext",
  "routingSafe",
  "generalChat",
];

const workloadLabels: Record<Workload, string> = {
  support: "Support",
  batchable: "Batch jobs",
  agentic: "Agent workflows",
  longContext: "Long context",
  routingSafe: "Simple tasks",
  generalChat: "General chat",
};

const workloadHints: Record<Workload, string> = {
  support: "Support replies and ticket triage",
  batchable: "Bulk or async work",
  agentic: "Tool-calling agents",
  longContext: "Large prompts and RAG",
  routingSafe: "Classification and extraction",
  generalChat: "Open-ended assistants",
};

// Current SDK-wrapper benchmark model, after holdback, SDK overhead, and the
// 25% gain-share fee. Values are net savings rates as percentages.
const rates: Record<Workload, Rates> = {
  support: { conservative: 9.546, realistic: 16.1407, optimistic: 24.4298 },
  batchable: { conservative: 8.464, realistic: 15.2006, optimistic: 23.5368 },
  agentic: { conservative: 3.6807, realistic: 6.7992, optimistic: 10.2417 },
  longContext: { conservative: 2.5922, realistic: 4.9648, optimistic: 8.2554 },
  routingSafe: { conservative: 3.9478, realistic: 8.1396, optimistic: 12.1457 },
  generalChat: { conservative: -0.1007, realistic: -0.0683, optimistic: 0.0217 },
};

const defaultMix: Record<Workload, number> = {
  support: 30,
  batchable: 15,
  agentic: 15,
  longContext: 15,
  routingSafe: 15,
  generalChat: 10,
};

const presets: Array<{ label: string; mix: Record<Workload, number> }> = [
  { label: "Balanced", mix: defaultMix },
  {
    label: "Support-heavy",
    mix: {
      support: 55,
      batchable: 10,
      agentic: 10,
      longContext: 10,
      routingSafe: 10,
      generalChat: 5,
    },
  },
  {
    label: "Batch-heavy",
    mix: {
      support: 15,
      batchable: 45,
      agentic: 10,
      longContext: 10,
      routingSafe: 15,
      generalChat: 5,
    },
  },
  {
    label: "Mostly chat",
    mix: {
      support: 10,
      batchable: 5,
      agentic: 5,
      longContext: 10,
      routingSafe: 10,
      generalChat: 60,
    },
  },
];

function formatMoney(value: number): string {
  const sign = value < 0 ? "-" : "";
  const abs = Math.abs(Math.round(value));
  return `${sign}$${abs.toLocaleString("en-US")}`;
}

function formatPercent(value: number): string {
  return `${value >= 0 ? "" : "-"}${Math.abs(value).toFixed(1)}%`;
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function parseNumericInput(value: string, fallback: number): number {
  if (value.trim() === "") return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function SavingsCalculator() {
  const [spend, setSpend] = useState(25000);
  const [mix, setMix] = useState<Record<Workload, number>>(defaultMix);

  const total = useMemo(
    () => workloadOrder.reduce((sum, workload) => sum + mix[workload], 0),
    [mix],
  );
  const balanced = Math.round(total) === 100;

  const weighted = useMemo(() => {
    let conservative = 0;
    let realistic = 0;
    let optimistic = 0;

    for (const workload of workloadOrder) {
      const share = mix[workload] / 100;
      conservative += share * rates[workload].conservative;
      realistic += share * rates[workload].realistic;
      optimistic += share * rates[workload].optimistic;
    }

    return { conservative, realistic, optimistic };
  }, [mix]);

  const monthly = {
    conservative: (spend * weighted.conservative) / 100,
    realistic: (spend * weighted.realistic) / 100,
    optimistic: (spend * weighted.optimistic) / 100,
  };

  const notAFit = balanced && monthly.realistic <= 0;

  function setSpendValue(next: number) {
    setSpend(clamp(Math.round(next), 0, 500000));
  }

  function setMixValue(workload: Workload, next: number) {
    setMix((previous) => ({
      ...previous,
      [workload]: clamp(Math.round(next), 0, 100),
    }));
  }

  function balanceMix() {
    if (total === 0) {
      setMix(defaultMix);
      return;
    }

    const scale = 100 / total;
    const scaled = workloadOrder.map((workload) => ({
      workload,
      raw: mix[workload] * scale,
    }));
    const floored = scaled.map((item) => ({
      ...item,
      floor: Math.floor(item.raw),
    }));
    let remainder = 100 - floored.reduce((sum, item) => sum + item.floor, 0);

    floored
      .map((item) => ({ ...item, fraction: item.raw - item.floor }))
      .sort((a, b) => b.fraction - a.fraction)
      .forEach((item) => {
        if (remainder > 0) {
          item.floor += 1;
          remainder -= 1;
        }
      });

    const next = {} as Record<Workload, number>;
    for (const item of floored) {
      next[item.workload] = item.floor;
    }
    setMix(next);
  }

  return (
    <section id="calculator" className="border-b border-border bg-background">
      <div className="mx-auto max-w-[1400px] px-6 md:px-10">
        <div className="grid gap-10 border-b border-border py-16 md:grid-cols-12 md:py-24">
          <div className="md:col-span-5">
            <div className="mono mb-4 text-[11px] uppercase tracking-[0.28em] text-ink-soft">
              Section 02 - Estimator
            </div>
            <h2 className="text-[36px] font-medium leading-[1.05] tracking-[-0.02em] text-ink md:text-[48px]">
              Savings calculator
            </h2>
          </div>
          <div className="max-w-xl md:col-span-6 md:col-start-7">
            <p className="text-[16px] leading-[1.6] text-ink-soft">
              Estimate potential net savings from your current AI spend and workload mix. This assumes the production
              SDK integration and a 25% fee.
            </p>
            <div className="mono mt-6 border-t border-border pt-4 text-[11px] uppercase tracking-[0.24em] text-ink-soft">
              Estimate only - billing uses verified production savings
            </div>
          </div>
        </div>

        <div className="grid gap-0 md:grid-cols-12">
          <div className="border-b border-border p-6 md:col-span-7 md:border-b-0 md:border-r md:p-12">
            <div>
              <div className="mono mb-3 flex flex-wrap items-center justify-between gap-4 text-[10px] uppercase tracking-[0.28em] text-ink-soft">
                <span>Monthly AI spend</span>
                <input
                  type="number"
                  min={0}
                  max={500000}
                  step={1000}
                  value={spend}
                  onChange={(event) => setSpendValue(parseNumericInput(event.target.value, 0))}
                  className="h-9 w-36 border border-border bg-background px-3 text-right text-[12px] text-ink outline-none focus:border-ink"
                  aria-label="Monthly AI spend"
                />
              </div>
              <input
                type="range"
                min={0}
                max={500000}
                step={1000}
                value={spend}
                onChange={(event) => setSpendValue(Number(event.target.value))}
                className="w-full accent-[color:var(--color-blueprint)]"
                aria-label="Monthly AI spend slider"
              />
              <div className="mono mt-2 flex justify-between text-[10px] uppercase tracking-[0.22em] text-ink-soft">
                <span>$0</span>
                <span>$500k</span>
              </div>
            </div>

            <div className="mt-10">
              <div className="mono mb-4 flex flex-wrap items-center justify-between gap-3 text-[10px] uppercase tracking-[0.28em] text-ink-soft">
                <span>Traffic mix</span>
                <span className={balanced ? "text-ink" : "text-blueprint"}>
                  {Math.round(total)}% total
                  {!balanced ? (
                    <>
                      {" - "}
                      <button
                        type="button"
                        onClick={balanceMix}
                        className="underline underline-offset-2 hover:text-ink"
                      >
                        Balance to 100%
                      </button>
                    </>
                  ) : null}
                </span>
              </div>

              <div className="mb-6 flex flex-wrap gap-2">
                {presets.map((preset) => (
                  <button
                    key={preset.label}
                    type="button"
                    onClick={() => setMix(preset.mix)}
                    className="mono border border-border px-3 py-2 text-[10px] uppercase tracking-[0.2em] text-ink-soft transition-colors hover:border-ink hover:text-ink"
                  >
                    {preset.label}
                  </button>
                ))}
              </div>

              <div className="grid gap-5">
                {workloadOrder.map((workload) => (
                  <div key={workload}>
                    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
                      <div>
                        <span className="text-[14px] font-medium text-ink">{workloadLabels[workload]}</span>
                        <span className="ml-2 text-[12px] text-ink-soft">{workloadHints[workload]}</span>
                      </div>
                      <label className="mono flex items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-ink-soft">
                        <input
                          type="number"
                          min={0}
                          max={100}
                          step={1}
                          value={mix[workload]}
                          onChange={(event) =>
                            setMixValue(workload, parseNumericInput(event.target.value, 0))
                          }
                          className="h-8 w-16 border border-border bg-background px-2 text-right text-[12px] text-ink outline-none focus:border-ink"
                          aria-label={`${workloadLabels[workload]} percentage`}
                        />
                        %
                      </label>
                    </div>
                    <input
                      type="range"
                      min={0}
                      max={100}
                      step={1}
                      value={mix[workload]}
                      onChange={(event) => setMixValue(workload, Number(event.target.value))}
                      className="mt-2 w-full accent-[color:var(--color-blueprint)]"
                      aria-label={`${workloadLabels[workload]} share slider`}
                    />
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="bg-ink p-6 text-primary-foreground md:col-span-5 md:p-12">
            <div className="mono text-[10px] uppercase tracking-[0.28em] text-white/60">
              Estimated monthly net savings
            </div>

            {balanced ? (
              <>
                <div className="mt-3 text-[52px] font-medium leading-none tracking-[-0.03em] text-white md:text-[72px]">
                  {notAFit ? "$0" : formatMoney(monthly.realistic)}
                </div>
                <div className="mono mt-3 text-[11px] uppercase tracking-[0.22em] text-white/60">
                  {notAFit
                    ? "This mix may not be a strong fit"
                    : `Realistic - ${formatPercent(weighted.realistic)} net savings`}
                </div>

                <div className="mt-8 grid grid-cols-1 gap-px bg-white/20 text-ink sm:grid-cols-3">
                  {(["conservative", "realistic", "optimistic"] as const).map((key) => (
                    <div key={key} className="bg-ink p-4">
                      <div className="mono text-[10px] uppercase tracking-[0.22em] text-white/50">
                        {key}
                      </div>
                      <div className="mt-2 text-[22px] font-medium text-white">
                        {notAFit ? "$0" : formatMoney(monthly[key])}
                      </div>
                      <div className="mono mt-1 text-[10px] uppercase tracking-[0.18em] text-white/50">
                        {formatPercent(weighted[key])}
                      </div>
                    </div>
                  ))}
                </div>

                <div className="mono mt-8 border-t border-white/20 pt-5 text-[11px] uppercase tracking-[0.22em] text-white/60">
                  Annual realistic estimate
                  <div className="mt-2 text-[24px] tracking-normal text-white">
                    {notAFit ? "$0" : formatMoney(monthly.realistic * 12)}
                  </div>
                </div>
              </>
            ) : (
              <div className="mt-8 border-t border-white/20 pt-6">
                <div className="text-[28px] font-medium leading-tight text-white">
                  Balance traffic mix to 100%.
                </div>
                <p className="mt-4 text-[14px] leading-6 text-white/60">
                  The estimate stays hidden until the workload percentages describe one complete month of traffic.
                </p>
              </div>
            )}

            <div className="mt-8 border-t border-white/20 pt-6">
              <div className="mono mb-3 text-[10px] uppercase tracking-[0.28em] text-white/60">
                Traffic mix
              </div>
              <div className="flex h-2 w-full overflow-hidden">
                {workloadOrder.map((workload, index) => {
                  const percent = total > 0 ? (mix[workload] / total) * 100 : 0;
                  if (percent === 0) return null;
                  const opacity = Math.max(0.2, 1 - index * 0.13);
                  return (
                    <div
                      key={workload}
                      style={{
                        width: `${percent}%`,
                        background: `rgba(255,255,255,${opacity})`,
                      }}
                      title={`${workloadLabels[workload]} - ${mix[workload]}%`}
                    />
                  );
                })}
              </div>
            </div>

            <div className="mono mt-8 border-t border-white/20 pt-4 text-[10px] uppercase leading-relaxed tracking-[0.22em] text-white/60">
              Based on current SDK benchmark ranges. Actual savings depend on your traffic and are billed only after
              Varsten verifies production savings.
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
