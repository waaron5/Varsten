// Server Component (no hooks) rendered by each segment's loading.tsx. It shows a
// structured page skeleton inside the persistent AppShell during route
// transitions, so navigation reveals layout immediately instead of a blank pane
// or a lone centered spinner. The shape (stat row + chart block + table block)
// generically matches the Dashboard, Proof, Analysis, and Engine pages.

function Bar({ width, height = 14 }: { width: string | number; height?: number }) {
  return <div className="sk" style={{ width, height }} />;
}

function CardSkeleton({ height }: { height: number }) {
  return (
    <div className="card" style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12 }}>
      <Bar width={140} height={12} />
      <div className="sk" style={{ width: "100%", height, borderRadius: 8 }} />
    </div>
  );
}

export function RouteSkeleton() {
  return (
    <div className="view" aria-busy="true" aria-label="Loading">
      <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 24 }}>
        <Bar width={220} height={24} />
        <Bar width={320} height={12} />
      </div>

      <div className="sk-stat-row" style={{ marginBottom: 16 }}>
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="card" style={{ padding: 16, display: "flex", flexDirection: "column", gap: 10 }}>
            <Bar width="60%" height={11} />
            <Bar width="45%" height={22} />
          </div>
        ))}
      </div>

      <div style={{ display: "grid", gap: 16 }}>
        <CardSkeleton height={260} />
        <CardSkeleton height={180} />
      </div>
    </div>
  );
}
