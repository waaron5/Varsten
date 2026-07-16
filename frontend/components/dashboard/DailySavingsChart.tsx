import { PanelEmpty } from "./primitives";
import {
  compactMoneyDisplay,
  shortChartDate,
  type DashboardDailyPointView,
  type DashboardStatView,
} from "./viewModel";

type DrawableDailyPoint = DashboardDailyPointView & {
  actual: number;
  savings: number;
  total: number;
};

function hasChartValues(point: DashboardDailyPointView): point is DrawableDailyPoint {
  return point.actual !== null && point.savings !== null && point.total !== null;
}

function Stat({ stat, bordered }: { stat: DashboardStatView; bordered?: boolean }) {
  return (
    <div className={bordered ? "bordered" : undefined}>
      <span>{stat.label}</span>
      <b className={stat.positive ? "positive" : undefined}>{stat.value}</b>
    </div>
  );
}

export function DailySavingsChart({ data, stats }: { data: DashboardDailyPointView[]; stats: DashboardStatView[] }) {
  const chartData = data.filter(hasChartValues);
  const width = 1400;
  const height = 340;
  const padL = 56;
  const padR = 16;
  const padT = 16;
  const padB = 32;
  const innerW = width - padL - padR;
  const innerH = height - padT - padB;
  const max = Math.max(...chartData.map((point) => point.total), 0) * 1.1 || 1;
  const step = chartData.length ? innerW / chartData.length : innerW;
  const barW = Math.max(3, step * 0.7);
  const ticks = Array.from({ length: 5 }, (_, index) => (max / 4) * index);
  const showLabelEvery = Math.max(1, Math.ceil(chartData.length / 10));

  return (
    <article className="lv-panel lv-daily-panel">
      <header className="lv-panel-head">
        <div>
          <div className="lv-section-kicker">Section 01 · Trend</div>
          <h3>Daily Savings</h3>
        </div>
        <ul className="lv-chart-legend" aria-label="Chart legend">
          <li><span className="actual" aria-hidden="true" />Actual spend</li>
          <li><span className="savings" aria-hidden="true" />Savings</li>
        </ul>
      </header>

      {chartData.length ? (
        <>
          <div className="lv-svg-chart">
            <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Daily stacked spend and savings">
              {ticks.map((value, index) => {
                const y = padT + innerH - (value / max) * innerH;
                return (
                  <g key={index}>
                    <line x1={padL} x2={width - padR} y1={y} y2={y} />
                    <text x={padL - 8} y={y + 3} textAnchor="end">{compactMoneyDisplay(value)}</text>
                  </g>
                );
              })}
              {chartData.map((point, index) => {
                const x = padL + step * index + (step - barW) / 2;
                const actualH = (point.actual / max) * innerH;
                const savingsH = (point.savings / max) * innerH;
                const yTop = padT + innerH - (point.total / max) * innerH;
                return (
                  <g key={point.date}>
                    <rect x={x} y={padT + innerH - actualH} width={barW} height={actualH} className="actual">
                      <title>{`${point.date} · Actual ${point.actualDisplay}`}</title>
                    </rect>
                    <rect x={x} y={yTop} width={barW} height={savingsH} className="savings">
                      <title>{`${point.date} · Savings ${point.savingsDisplay}`}</title>
                    </rect>
                    {index % showLabelEvery === 0 ? (
                      <text x={x + barW / 2} y={height - 10} textAnchor="middle">{shortChartDate(point.date)}</text>
                    ) : null}
                  </g>
                );
              })}
            </svg>
          </div>
          <div className="lv-daily-stats">
            {stats.map((stat, index) => <Stat key={stat.label} stat={stat} bordered={index > 0} />)}
          </div>
        </>
      ) : (
        <PanelEmpty label={data.length ? "Savings trend is unavailable for this period." : "Send traffic through Varsten to build your savings trend."} />
      )}
    </article>
  );
}
