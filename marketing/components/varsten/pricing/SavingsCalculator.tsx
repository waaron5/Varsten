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

type Scenario = keyof Rates;
const scenarios = ["conservative", "realistic", "optimistic"] as const satisfies readonly Scenario[];

function weightedRates(mix: Record<Workload, number>): Rates {
  return workloadOrder.reduce<Rates>(
    (weighted, workload) => {
      const share = mix[workload] / 100;
      return {
        conservative: weighted.conservative + share * rates[workload].conservative,
        realistic: weighted.realistic + share * rates[workload].realistic,
        optimistic: weighted.optimistic + share * rates[workload].optimistic,
      };
    },
    { conservative: 0, realistic: 0, optimistic: 0 },
  );
}

function monthlySavings(spend: number, weighted: Rates): Rates {
  return {
    conservative: (spend * weighted.conservative) / 100,
    realistic: (spend * weighted.realistic) / 100,
    optimistic: (spend * weighted.optimistic) / 100,
  };
}

function balancedMix(mix: Record<Workload, number>, total: number): Record<Workload, number> {
  if (total === 0) return defaultMix;
  const scale = 100 / total;
  const floored = workloadOrder.map((workload) => {
    const raw = mix[workload] * scale;
    return { workload, floor: Math.floor(raw), fraction: raw - Math.floor(raw) };
  });
  let remainder = 100 - floored.reduce((sum, item) => sum + item.floor, 0);
  const ranked = [...floored].sort((a, b) => b.fraction - a.fraction);
  for (const item of ranked) {
    if (remainder <= 0) break;
    item.floor += 1;
    remainder -= 1;
  }
  return Object.fromEntries(floored.map((item) => [item.workload, item.floor])) as Record<Workload, number>;
}

function useCalculatorState() {
  const [spend, setSpend] = useState(25000);
  const [mix, setMix] = useState<Record<Workload, number>>(defaultMix);

  const total = useMemo(
    () => workloadOrder.reduce((sum, workload) => sum + mix[workload], 0),
    [mix],
  );
  const balanced = Math.round(total) === 100;
  const weighted = useMemo(() => weightedRates(mix), [mix]);
  const monthly = monthlySavings(spend, weighted);
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
    setMix(balancedMix(mix, total));
  }

  return { balanceMix, balanced, mix, monthly, notAFit, setMix, setMixValue, setSpendValue, spend, total, weighted };
}

export function SavingsCalculator() {
  const calculator = useCalculatorState();

  return (
    <section id="calculator" className="border-b border-border bg-background">
      <div className="mx-auto max-w-[1400px] px-6 md:px-10">
        <CalculatorHeader />

        <div className="grid gap-0 md:grid-cols-12">
          <div className="border-b border-border p-6 md:col-span-7 md:border-b-0 md:border-r md:p-12">
            <SpendControl spend={calculator.spend} setSpendValue={calculator.setSpendValue} />
            <MixControls calculator={calculator} />
          </div>

          <EstimatePanel calculator={calculator} />
        </div>
      </div>
    </section>
  );
}

function CalculatorHeader() {
  return (
    <div className="grid gap-10 border-b border-border py-16 md:grid-cols-12 md:py-24">
      <div className="md:col-span-5">
        <div className="mono mb-4 text-[11px] uppercase tracking-[0.28em] text-ink-soft">Section 02 - Estimator</div>
        <h2 className="text-[36px] font-medium leading-[1.05] tracking-[-0.02em] text-ink md:text-[48px]">
          Savings calculator
        </h2>
      </div>
      <div className="max-w-xl md:col-span-6 md:col-start-7">
        <p className="text-[16px] leading-[1.6] text-ink-soft">
          Estimate potential net savings from your current AI spend and workload mix. This assumes the production SDK
          integration and a 25% fee.
        </p>
        <div className="mono mt-6 border-t border-border pt-4 text-[11px] uppercase tracking-[0.24em] text-ink-soft">
          Estimate only - billing uses verified production savings
        </div>
      </div>
    </div>
  );
}

function SpendControl({ setSpendValue, spend }: { setSpendValue: (next: number) => void; spend: number }) {
  return (
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
  );
}

function MixControls({ calculator }: { calculator: ReturnType<typeof useCalculatorState> }) {
  return (
    <div className="mt-10">
      <MixHeader balanced={calculator.balanced} onBalance={calculator.balanceMix} total={calculator.total} />
      <PresetButtons onSelect={calculator.setMix} />
      <div className="grid gap-5">
        {workloadOrder.map((workload) => (
          <WorkloadControl
            key={workload}
            mix={calculator.mix}
            setMixValue={calculator.setMixValue}
            workload={workload}
          />
        ))}
      </div>
    </div>
  );
}

function MixHeader({ balanced, onBalance, total }: { balanced: boolean; onBalance: () => void; total: number }) {
  return (
    <div className="mono mb-4 flex flex-wrap items-center justify-between gap-3 text-[10px] uppercase tracking-[0.28em] text-ink-soft">
      <span>Traffic mix</span>
      <span className={balanced ? "text-ink" : "text-blueprint"}>
        {Math.round(total)}% total
        <BalanceButton balanced={balanced} onBalance={onBalance} />
      </span>
    </div>
  );
}

function BalanceButton({ balanced, onBalance }: { balanced: boolean; onBalance: () => void }) {
  if (balanced) return null;
  return (
    <>
      {" - "}
      <button type="button" onClick={onBalance} className="underline underline-offset-2 hover:text-ink">
        Balance to 100%
      </button>
    </>
  );
}

function PresetButtons({ onSelect }: { onSelect: (mix: Record<Workload, number>) => void }) {
  return (
    <div className="mb-6 flex flex-wrap gap-2">
      {presets.map((preset) => (
        <button
          key={preset.label}
          type="button"
          onClick={() => onSelect(preset.mix)}
          className="mono border border-border px-3 py-2 text-[10px] uppercase tracking-[0.2em] text-ink-soft transition-colors hover:border-ink hover:text-ink"
        >
          {preset.label}
        </button>
      ))}
    </div>
  );
}

function WorkloadControl({
  mix,
  setMixValue,
  workload,
}: {
  mix: Record<Workload, number>;
  setMixValue: (workload: Workload, next: number) => void;
  workload: Workload;
}) {
  return (
    <div>
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
            onChange={(event) => setMixValue(workload, parseNumericInput(event.target.value, 0))}
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
  );
}

function EstimatePanel({ calculator }: { calculator: ReturnType<typeof useCalculatorState> }) {
  return (
    <div className="bg-ink p-6 text-primary-foreground md:col-span-5 md:p-12">
      <div className="mono text-[10px] uppercase tracking-[0.28em] text-white/60">Estimated monthly net savings</div>
      {calculator.balanced ? <BalancedEstimate calculator={calculator} /> : <UnbalancedEstimate />}
      <MixBar mix={calculator.mix} total={calculator.total} />
      <div className="mono mt-8 border-t border-white/20 pt-4 text-[10px] uppercase leading-relaxed tracking-[0.22em] text-white/60">
        Based on current SDK benchmark ranges. Actual savings depend on your traffic and are billed only after Varsten
        verifies production savings.
      </div>
    </div>
  );
}

function displaySavings(value: number, notAFit: boolean): string {
  return notAFit ? "$0" : formatMoney(value);
}

function BalancedEstimate({ calculator }: { calculator: ReturnType<typeof useCalculatorState> }) {
  return (
    <>
      <div className="mt-3 text-[52px] font-medium leading-none tracking-[-0.03em] text-white md:text-[72px]">
        {displaySavings(calculator.monthly.realistic, calculator.notAFit)}
      </div>
      <div className="mono mt-3 text-[11px] uppercase tracking-[0.22em] text-white/60">
        {calculator.notAFit
          ? "This mix may not be a strong fit"
          : `Realistic - ${formatPercent(calculator.weighted.realistic)} net savings`}
      </div>
      <ScenarioGrid calculator={calculator} />
      <AnnualEstimate calculator={calculator} />
    </>
  );
}

function ScenarioGrid({ calculator }: { calculator: ReturnType<typeof useCalculatorState> }) {
  return (
    <div className="mt-8 grid grid-cols-1 gap-px bg-white/20 text-ink sm:grid-cols-3">
      {scenarios.map((key) => (
        <div key={key} className="bg-ink p-4">
          <div className="mono text-[10px] uppercase tracking-[0.22em] text-white/50">{key}</div>
          <div className="mt-2 text-[22px] font-medium text-white">
            {displaySavings(calculator.monthly[key], calculator.notAFit)}
          </div>
          <div className="mono mt-1 text-[10px] uppercase tracking-[0.18em] text-white/50">
            {formatPercent(calculator.weighted[key])}
          </div>
        </div>
      ))}
    </div>
  );
}

function AnnualEstimate({ calculator }: { calculator: ReturnType<typeof useCalculatorState> }) {
  return (
    <div className="mono mt-8 border-t border-white/20 pt-5 text-[11px] uppercase tracking-[0.22em] text-white/60">
      Annual realistic estimate
      <div className="mt-2 text-[24px] tracking-normal text-white">
        {displaySavings(calculator.monthly.realistic * 12, calculator.notAFit)}
      </div>
    </div>
  );
}

function UnbalancedEstimate() {
  return (
    <div className="mt-8 border-t border-white/20 pt-6">
      <div className="text-[28px] font-medium leading-tight text-white">Balance traffic mix to 100%.</div>
      <p className="mt-4 text-[14px] leading-6 text-white/60">
        The estimate stays hidden until the workload percentages describe one complete month of traffic.
      </p>
    </div>
  );
}

function MixBar({ mix, total }: { mix: Record<Workload, number>; total: number }) {
  return (
    <div className="mt-8 border-t border-white/20 pt-6">
      <div className="mono mb-3 text-[10px] uppercase tracking-[0.28em] text-white/60">Traffic mix</div>
      <div className="flex h-2 w-full overflow-hidden">
        {workloadOrder.map((workload, index) => (
          <MixBarSegment key={workload} index={index} mix={mix} total={total} workload={workload} />
        ))}
      </div>
    </div>
  );
}

function MixBarSegment({
  index,
  mix,
  total,
  workload,
}: {
  index: number;
  mix: Record<Workload, number>;
  total: number;
  workload: Workload;
}) {
  const percent = total > 0 ? (mix[workload] / total) * 100 : 0;
  if (percent === 0) return null;
  const opacity = Math.max(0.2, 1 - index * 0.13);
  return (
    <div
      style={{
        width: `${percent}%`,
        background: `rgba(255,255,255,${opacity})`,
      }}
      title={`${workloadLabels[workload]} - ${mix[workload]}%`}
    />
  );
}
