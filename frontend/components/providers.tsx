// Kept as a passthrough so layout wiring (and step-12 session auth) has a home.
export function ApiKeyProvider({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
