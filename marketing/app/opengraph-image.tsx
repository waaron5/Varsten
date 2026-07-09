import { ImageResponse } from "next/og";

export const size = {
  width: 1200,
  height: 630,
};

export const contentType = "image/png";

export default function OpenGraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: "#ffffff",
          color: "#111111",
          padding: 64,
          fontFamily: "Inter, Arial, sans-serif",
          border: "1px solid #e5e5e5",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
          <div style={{ width: 28, height: 28, background: "#1447e6" }} />
          <div style={{ fontSize: 36, fontWeight: 700, letterSpacing: -1 }}>Varsten</div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
          <div
            style={{
              color: "#6b6b6b",
              fontFamily: "JetBrains Mono, monospace",
              fontSize: 18,
              letterSpacing: 6,
              textTransform: "uppercase",
            }}
          >
            AI cost optimization engine
          </div>
          <div style={{ maxWidth: 900, fontSize: 78, fontWeight: 720, lineHeight: 1.02, letterSpacing: -3 }}>
            Reduce AI spend and prove every dollar saved.
          </div>
        </div>
      </div>
    ),
    size,
  );
}
