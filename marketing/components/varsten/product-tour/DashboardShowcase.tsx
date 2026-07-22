"use client";

import { useState } from "react";

const periods = ["Month", "Quarter", "Year"] as const;

const periodData = {
  Month: {
    net: "$18.4k",
    gross: "$24.6k",
    baseline: "$96.8k",
    actual: "$72.2k",
    netDelta: "12.8%",
    grossDelta: "10.4%",
    baselineDelta: "3.1%",
    actualDelta: "7.6%",
  },
  Quarter: {
    net: "$51.7k",
    gross: "$69.1k",
    baseline: "$281k",
    actual: "$212k",
    netDelta: "16.2%",
    grossDelta: "13.9%",
    baselineDelta: "5.4%",
    actualDelta: "8.2%",
  },
  Year: {
    net: "$194k",
    gross: "$259k",
    baseline: "$1.08m",
    actual: "$821k",
    netDelta: "22.1%",
    grossDelta: "19.7%",
    baselineDelta: "8.8%",
    actualDelta: "11.3%",
  },
} as const;

const chartWeights = [
  [30, 12], [42, 16], [36, 14], [54, 21], [48, 18], [63, 25], [58, 21],
  [71, 28], [61, 24], [76, 30], [69, 27], [82, 32], [74, 28], [88, 35],
  [78, 31], [91, 36], [84, 33], [96, 38], [87, 34], [102, 40], [94, 37],
  [108, 42], [99, 39], [114, 45], [104, 41], [119, 47], [111, 44], [124, 49],
];

const monthActualUsd = 72_200;
const monthSavingsUsd = 24_600;

function allocateTotal(weights: number[], total: number): number[] {
  const weightTotal = weights.reduce((sum, value) => sum + value, 0);
  const allocated = weights.map((value) => Math.floor((value / weightTotal) * total));
  allocated[allocated.length - 1] += total - allocated.reduce((sum, value) => sum + value, 0);
  return allocated;
}

const actualByDay = allocateTotal(chartWeights.map(([actual]) => actual), monthActualUsd);
const savingsByDay = allocateTotal(chartWeights.map(([, savings]) => savings), monthSavingsUsd);
const chartBars = actualByDay.map((actual, index) => ({ actual, savings: savingsByDay[index] }));

function usd(value: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value);
}

const leverRows = [
  { id: "01", name: "Semantic cache", value: "$9,840", share: "40.0%", width: "100%", opacity: 1 },
  { id: "02", name: "Model downshift", value: "$6,396", share: "26.0%", width: "65%", opacity: 0.78 },
  { id: "03", name: "Prompt caching", value: "$4,182", share: "17.0%", width: "43%", opacity: 0.58 },
  { id: "04", name: "Token trimming", value: "$2,706", share: "11.0%", width: "28%", opacity: 0.42 },
  { id: "05", name: "Batching", value: "$1,476", share: "6.0%", width: "15%", opacity: 0.3 },
];

const drivers = {
  team: [
    { name: "Product", value: "$29,602", share: "41.0%", width: "100%", opacity: 1 },
    { name: "Support", value: "$19,494", share: "27.0%", width: "66%", opacity: 0.78 },
    { name: "Growth", value: "$14,440", share: "20.0%", width: "49%", opacity: 0.58 },
    { name: "Internal", value: "$8,664", share: "12.0%", width: "29%", opacity: 0.42 },
  ],
  feature: [
    { name: "AI assistant", value: "$34,656", share: "48.0%", width: "100%", opacity: 1 },
    { name: "Document search", value: "$20,216", share: "28.0%", width: "58%", opacity: 0.78 },
    { name: "Ticket summary", value: "$10,108", share: "14.0%", width: "29%", opacity: 0.58 },
    { name: "Other", value: "$7,220", share: "10.0%", width: "21%", opacity: 0.42 },
  ],
} as const;

function PeriodControls({ period, setPeriod }: { period: keyof typeof periodData; setPeriod: (period: keyof typeof periodData) => void }) {
  return (
    <div className="inline-flex border border-border bg-white" role="tablist" aria-label="Dashboard reporting period preview">
      {periods.map((item) => (
        <button
          key={item}
          type="button"
          role="tab"
          aria-selected={period === item}
          className={`mono h-10 px-4 text-[10px] uppercase tracking-[0.18em] transition-colors ${period === item ? "bg-ink text-white" : "text-ink-soft hover:text-ink"}`}
          onClick={() => setPeriod(item)}
        >
          {item}
        </button>
      ))}
    </div>
  );
}

function KpiStrip({ period }: { period: keyof typeof periodData }) {
  const values = periodData[period];
  const cards = [
    ["Net Realized Savings", values.net, values.netDelta, "After optimization fee", true],
    ["Gross Savings", values.gross, values.grossDelta, "Total cost eliminated pre-fee", false],
    ["Baseline Cost", values.baseline, values.baselineDelta, "List-price spend without Varsten", false],
    ["Actual Spend", values.actual, values.actualDelta, "Paid to providers this period", false],
  ] as const;

  return (
    <div className="grid grid-cols-1 gap-px border border-border bg-border sm:grid-cols-2 xl:grid-cols-4">
      {cards.map(([label, value, delta, detail, hero]) => <KpiCard key={label} label={label} value={value} delta={delta} detail={detail} hero={hero} />)}
    </div>
  );
}

function KpiCard({ label, value, delta, detail, hero }: { label: string; value: string; delta: string; detail: string; hero: boolean }) {
  const tone = hero ? {
    card: "bg-ink text-white",
    label: "text-white/55",
    secondary: "text-white/65",
    delta: "bg-white/10 text-white",
    detail: "text-white/60",
  } : {
    card: "bg-white text-ink",
    label: "text-ink-soft",
    secondary: "text-ink-soft",
    delta: "bg-blueprint-soft text-blueprint",
    detail: "text-ink-soft",
  };
  return (
    <article className={`flex min-h-[218px] flex-col justify-between p-7 ${tone.card}`}>
      <div className={`mono flex justify-between gap-3 text-[10px] uppercase tracking-[0.24em] ${tone.label}`}>
        <span>{label}</span><KpiHeroDot visible={hero} />
      </div>
      <div className="mt-10">
        <div className="text-[42px] font-medium leading-none tracking-[-0.025em]">{value}</div>
        <div className={`mt-4 flex items-center gap-3 text-[12px] ${tone.secondary}`}>
          <span className={`mono px-2 py-1 text-[9px] tracking-[0.12em] ${tone.delta}`}>↑ {delta}</span>
          <span>vs. prior period</span>
        </div>
        <p className={`mt-4 text-[12px] ${tone.detail}`}>{detail}</p>
      </div>
    </article>
  );
}

function KpiHeroDot({ visible }: { visible: boolean }) {
  if (!visible) return null;
  return <span className="text-blueprint">●</span>;
}

function PanelHeader({ section, title, children }: { section: string; title: string; children?: React.ReactNode }) {
  return (
    <header className="flex flex-col gap-4 p-6 sm:flex-row sm:items-start sm:justify-between sm:p-8">
      <div>
        <div className="mono text-[10px] uppercase tracking-[0.25em] text-ink-soft">{section}</div>
        <h3 className="mt-2 text-[21px] font-semibold tracking-[-0.01em] text-ink">{title}</h3>
      </div>
      {children}
    </header>
  );
}

function DailyChart() {
  const totalActual = chartBars.reduce((sum, point) => sum + point.actual, 0);
  const totalSavings = chartBars.reduce((sum, point) => sum + point.savings, 0);
  const totalBaseline = totalActual + totalSavings;
  const maxBaseline = Math.max(...chartBars.map((point) => point.actual + point.savings)) * 1.1;
  const chartBottom = 285;
  const chartTop = 45;
  const chartHeight = chartBottom - chartTop;
  const yTicks = Array.from({ length: 5 }, (_, index) => (maxBaseline / 4) * (4 - index));
  const stats = [
    ["Avg daily spend", usd(totalActual / chartBars.length)],
    ["Avg daily savings", usd(totalSavings / chartBars.length)],
    ["Effective savings rate", `${((totalSavings / totalBaseline) * 100).toFixed(1)}%`],
  ];
  return (
    <article className="border border-border bg-white">
      <PanelHeader section="Section 01 · Trend" title="Daily Savings">
        <div className="mono flex gap-5 text-[9px] uppercase tracking-[0.15em] text-ink-soft">
          <span className="flex items-center gap-2"><i className="h-2 w-2 bg-border-strong" />Actual spend</span>
          <span className="flex items-center gap-2"><i className="h-2 w-2 bg-blueprint" />Savings</span>
        </div>
      </PanelHeader>
      <div className="px-5 pb-2 sm:px-8">
        <svg viewBox="0 0 1200 330" className="block h-auto w-full" role="img" aria-label="Daily stacked actual spend and savings chart">
          {yTicks.map((value, index) => {
            const y = chartTop + index * (chartHeight / 4);
            return (
            <g key={y}>
              <line x1="54" x2="1184" y1={y} y2={y} stroke="#e5e5e5" />
              <text x="44" y={y + 4} textAnchor="end" fill="#6b6b6b" fontSize="10" fontFamily="monospace">{value >= 1000 ? `$${(value / 1000).toFixed(1)}k` : usd(value)}</text>
            </g>
            );
          })}
          {chartBars.map(({ actual, savings }, index) => {
            const x = 66 + index * 39;
            const actualHeight = (actual / maxBaseline) * chartHeight;
            const savingsHeight = (savings / maxBaseline) * chartHeight;
            const bottom = chartBottom;
            return (
              <g key={index}>
                <rect x={x} y={bottom - actualHeight} width="23" height={actualHeight} fill="#d4d4d4"><title>{`Day ${index + 1} · Actual ${usd(actual)}`}</title></rect>
                <rect x={x} y={bottom - actualHeight - savingsHeight} width="23" height={savingsHeight} fill="#1447e6"><title>{`Day ${index + 1} · Savings ${usd(savings)}`}</title></rect>
              </g>
            );
          })}
          <text x="77" y="315" textAnchor="middle" fill="#6b6b6b" fontSize="10" fontFamily="monospace">06-01</text>
          <text x="623" y="315" textAnchor="middle" fill="#6b6b6b" fontSize="10" fontFamily="monospace">06-15</text>
          <text x="1168" y="315" textAnchor="middle" fill="#6b6b6b" fontSize="10" fontFamily="monospace">06-28</text>
        </svg>
      </div>
      <div className="mx-5 mt-4 grid border-t border-border sm:mx-8 sm:grid-cols-3">
        {stats.map(([label, value], index) => (
          <div key={label} className={`py-5 sm:px-5 ${index ? "border-t border-border sm:border-l sm:border-t-0" : "sm:pl-0"}`}>
            <span className="mono block text-[9px] uppercase tracking-[0.22em] text-ink-soft">{label}</span>
            <b className="mt-2 block text-[20px] font-semibold text-ink">{value}</b>
          </div>
        ))}
      </div>
    </article>
  );
}

type RankedRowProps = { id?: string; name: string; value: string; share: string; width: string; opacity: number; gold?: boolean };

function RankedRow({ id, name, value, share, width, opacity, gold = false }: RankedRowProps) {
  const toneClass = gold ? "bg-[#b78935]" : "bg-blueprint";
  return (
    <li className="border-t border-border py-4 first:border-t-0">
      <div className="flex items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <RankedRowMarker id={id} opacity={opacity} toneClass={toneClass} />
          <span className="truncate text-[13px] text-ink">{name}</span>
          <RankedRowStatus visible={Boolean(id)} />
        </div>
        <div className="mono flex shrink-0 gap-4 text-[11px]"><span>{value}</span><span className="w-12 text-right text-[9px] tracking-[0.12em] text-ink-soft">{share}</span></div>
      </div>
      <div className="mt-2.5 h-1 bg-secondary"><span className={`block h-full ${toneClass}`} style={{ width, opacity }} /></div>
    </li>
  );
}

function RankedRowMarker({ id, opacity, toneClass }: { id?: string; opacity: number; toneClass: string }) {
  if (id) return <span className="mono text-[10px] tracking-[0.22em] text-ink-soft">{id}</span>;
  return <i className={`h-2.5 w-2.5 shrink-0 ${toneClass}`} style={{ opacity }} />;
}

function RankedRowStatus({ visible }: { visible: boolean }) {
  if (!visible) return null;
  return <span className="mono hidden items-center gap-1.5 text-[8px] uppercase tracking-[0.15em] text-blueprint sm:inline-flex"><i className="h-1.5 w-1.5 bg-blueprint" />Active</span>;
}

function SavingsLevers() {
  return (
    <article className="border border-border bg-white">
      <PanelHeader section="Section 02 · Mechanism" title="Savings by Lever" />
      <div className="mono flex h-11 items-end border-b border-border px-6 text-[10px] uppercase tracking-[0.24em] text-ink sm:px-8"><span className="border-b-2 border-ink pb-3">5 · 5 active</span></div>
      <div className="mx-6 my-6 flex h-3 overflow-hidden bg-secondary sm:mx-8">
        {[40, 26, 17, 11, 6].map((share, index) => <span key={share} className="h-full border-l border-white bg-blueprint first:border-l-0" style={{ width: `${share}%`, opacity: leverRows[index].opacity }} />)}
      </div>
      <ul className="px-6 sm:px-8">{leverRows.map((row) => <RankedRow key={row.id} {...row} />)}</ul>
      <footer className="mono flex justify-between border-t border-border px-6 py-5 text-[10px] uppercase tracking-[0.22em] text-ink-soft sm:px-8"><span>Gross savings</span><b className="text-[14px] tracking-normal text-ink">$24,600</b></footer>
    </article>
  );
}

function SpendDrivers() {
  const [tab, setTab] = useState<keyof typeof drivers>("team");
  return (
    <article className="border border-border bg-white">
      <PanelHeader section="Section 03 · Allocation" title="Spend Drivers" />
      <div className="mono flex h-11 items-end gap-6 border-b border-border px-6 text-[10px] uppercase tracking-[0.22em] text-ink-soft sm:px-8">
        {(["team", "feature"] as const).map((item) => <button key={item} type="button" onClick={() => setTab(item)} className={`pb-3 ${tab === item ? "border-b-2 border-ink text-ink" : ""}`}>By {item}</button>)}
      </div>
      <div className="mx-6 my-6 flex h-3 overflow-hidden bg-secondary sm:mx-8">
        {drivers[tab].map((row) => <span key={row.name} className="h-full border-l border-white bg-[#b78935] first:border-l-0" style={{ width: row.share, opacity: row.opacity }} />)}
      </div>
      <ul className="px-6 sm:px-8">{drivers[tab].map((row) => <RankedRow key={row.name} {...row} gold />)}</ul>
      <footer className="mono flex justify-between border-t border-border px-6 py-5 text-[10px] uppercase tracking-[0.22em] text-ink-soft sm:px-8"><span>Total spend</span><b className="text-[14px] tracking-normal text-ink">$72,200</b></footer>
    </article>
  );
}

function DataIntegrity() {
  return (
    <article className="border border-border bg-white">
      <PanelHeader section="Section 04 · Savings" title="Data Integrity"><span className="mono bg-[#edf8f0] px-2 py-1 text-[9px] uppercase tracking-[0.14em] text-[#267642]">Verified</span></PanelHeader>
      <div className="flex items-end gap-5 border-b border-border px-6 pb-8 sm:px-8">
        <div className="text-[68px] font-medium leading-[0.85] tracking-[-0.04em] text-ink">96</div>
        <div><div className="mono text-[9px] uppercase tracking-[0.22em] text-ink-soft">Confidence score</div><strong className="mt-2 flex items-center gap-2 text-[13px]"><span className="inline-flex h-4 w-4 items-center justify-center bg-[#267642] text-[9px] text-white">✓</span>High confidence</strong><p className="mt-1 text-[12px] text-ink-soft">Savings backed by direct ledger evidence.</p></div>
      </div>
      <ul className="px-6 sm:px-8">
        {[["Measured share", "94.2%", "Directly measured savings"], ["Verified savings", "$23,173", "Matched to provider usage"], ["Pricing coverage", "99.8%", "Requests with catalog pricing"]].map(([label, value, detail]) => (
          <li key={label} className="flex justify-between gap-5 border-t border-border py-5 first:border-t-0"><div><div className="mono text-[9px] uppercase tracking-[0.22em] text-ink-soft">{label}</div><div className="mt-1.5 text-[17px] font-semibold">{value}</div><p className="mt-1 text-[12px] text-ink-soft">{detail}</p></div><span className="mono h-fit bg-[#edf8f0] px-2 py-1 text-[8px] uppercase tracking-[0.14em] text-[#267642]">Verified</span></li>
        ))}
      </ul>
    </article>
  );
}

type ExhibitVariant = "first-wide" | "split";
type ExhibitProps = { number: string; title: string; body: string; children: React.ReactNode; variant: ExhibitVariant };

const EXHIBIT_STYLES: Record<ExhibitVariant, { spacing: string; layout: string; intro: string; content: string }> = {
  "first-wide": { spacing: "pb-24 pt-6 md:pb-36 md:pt-10", layout: "", intro: "max-w-xl", content: "mt-2 md:mt-8" },
  split: { spacing: "py-24 md:py-36", layout: "lg:grid-cols-[minmax(220px,0.34fr)_minmax(0,1fr)] lg:items-center lg:gap-20", intro: "max-w-sm", content: "" },
};

function Exhibit({ number, title, body, children, variant }: ExhibitProps) {
  const styles = EXHIBIT_STYLES[variant];
  return (
    <section className="border-b border-border bg-background">
      <div className={`mx-auto grid max-w-[1400px] gap-12 px-6 md:px-10 ${styles.spacing} ${styles.layout}`}>
        <div className={styles.intro}>
          <p className="mono text-[11px] uppercase tracking-[0.28em] text-ink-soft">{number}</p>
          <h2 className="mt-4 text-[30px] font-semibold leading-[1.12] tracking-[-0.02em] text-ink md:text-[42px]">{title}</h2>
          <p className="mt-5 text-[15px] leading-7 text-ink-soft">{body}</p>
        </div>
        <div className={styles.content}>{children}</div>
      </div>
    </section>
  );
}

export function DashboardShowcase() {
  const [period, setPeriod] = useState<keyof typeof periodData>("Month");

  return (
    <>
      <Exhibit number="01 · Period" title="Change the window. Keep the whole picture." body="Move between month, quarter, and year. Every number on the dashboard follows the same reporting period." variant="first-wide">
        <div className="mb-5 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <span className="mono text-[9px] uppercase tracking-[0.22em] text-ink-soft">Illustrative workspace · Demo data</span>
          <PeriodControls period={period} setPeriod={setPeriod} />
        </div>
        <KpiStrip period={period} />
      </Exhibit>

      <Exhibit number="02 · Trend" title="See savings happen day by day." body="Actual provider spend and eliminated cost stay separate, so the trend is readable at a glance." variant="split">
        <DailyChart />
      </Exhibit>

      <Exhibit number="03 · Mechanism" title="Know what created the savings." body="Every active lever has a measured contribution. Nothing disappears into a single unexplained total." variant="split">
        <SavingsLevers />
      </Exhibit>

      <Exhibit number="04 · Allocation" title="Find what drives the bill." body="Switch between teams and product features to see exactly where AI spend accumulates." variant="split">
        <SpendDrivers />
      </Exhibit>

      <Exhibit number="05 · Confidence" title="Trust the savings." body="Coverage and evidence are visible beside the result, giving finance and engineering the same answer." variant="split">
        <div className="mx-auto max-w-[620px]"><DataIntegrity /></div>
      </Exhibit>
    </>
  );
}
