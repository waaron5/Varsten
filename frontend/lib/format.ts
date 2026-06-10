export function usd(value: string | number, digits = 2): string {
  const n = typeof value === "string" ? parseFloat(value) : value;
  if (Number.isNaN(n)) return "$0.00";
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function compact(value: number): string {
  const unit = [
    { floor: 1e9, suffix: "B", digits: 2 },
    { floor: 1e6, suffix: "M", digits: 1 },
    { floor: 1e3, suffix: "K", digits: 1 },
  ].find(({ floor }) => value >= floor);
  return unit ? (value / unit.floor).toFixed(unit.digits) + unit.suffix : String(value);
}

export function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const secs = Math.round((Date.now() - then) / 1000);
  const mins = Math.round(secs / 60);
  const hours = Math.round(mins / 60);
  const days = Math.round(hours / 24);
  const label = [
    { active: secs < 5, value: "just now" },
    { active: secs < 60, value: `${secs}s ago` },
    { active: mins < 60, value: `${mins}m ago` },
    { active: hours < 24, value: `${hours}h ago` },
  ].find(({ active }) => active);
  return label?.value ?? `${days}d ago`;
}
