import { useEffect } from "react";

const DEFAULT_MAX_DURATION_MS = 20 * 60 * 1000;

export function useTimedPolling(active: boolean, intervalMs: number, onPoll: () => void | Promise<void>) {
  useEffect(() => {
    if (!active) return;

    const startedAt = Date.now();
    const id = window.setInterval(() => {
      if (Date.now() - startedAt > DEFAULT_MAX_DURATION_MS) {
        window.clearInterval(id);
        return;
      }
      void onPoll();
    }, intervalMs);

    return () => window.clearInterval(id);
  }, [active, intervalMs, onPoll]);
}
