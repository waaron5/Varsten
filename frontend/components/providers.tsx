"use client";

import { useCallback, useSyncExternalStore } from "react";

const STORAGE_KEY = "varsten_api_key";

// Module-level store so same-tab writes notify subscribers (the native "storage"
// event only fires in other tabs).
const listeners = new Set<() => void>();
function emit() {
  for (const l of listeners) l();
}
function subscribeKey(cb: () => void) {
  listeners.add(cb);
  window.addEventListener("storage", cb);
  return () => {
    listeners.delete(cb);
    window.removeEventListener("storage", cb);
  };
}
const getKeySnapshot = () => localStorage.getItem(STORAGE_KEY);
const getKeyServerSnapshot = () => null;

// false during SSR and the first client paint, true once mounted — without an
// effect, so it doesn't trip set-state-in-effect. Used to gate localStorage reads.
const noopSubscribe = () => () => {};
function useMounted() {
  return useSyncExternalStore(
    noopSubscribe,
    () => true,
    () => false,
  );
}

// Kept as a passthrough so layout wiring (and step-12 session auth) has a home.
export function ApiKeyProvider({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

export function useApiKey() {
  const mounted = useMounted();
  const stored = useSyncExternalStore(subscribeKey, getKeySnapshot, getKeyServerSnapshot);
  const apiKey = mounted ? stored : null;

  const setApiKey = useCallback((key: string) => {
    localStorage.setItem(STORAGE_KEY, key);
    emit();
  }, []);

  const clearApiKey = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY);
    emit();
  }, []);

  return { apiKey, ready: mounted, setApiKey, clearApiKey };
}
