"use client";

import { useEffect, useSyncExternalStore } from "react";

const DASHBOARD_PREVIEW_STORAGE_KEY = "varsten:dashboard-preview";

function readDashboardPreviewEnabled(): boolean {
  if (process.env.NODE_ENV !== "development" || typeof window === "undefined") return false;

  const queryValue = new URLSearchParams(window.location.search).get("dashboard_preview");
  if (queryValue === "1") return true;
  if (queryValue === "0") return false;
  return window.localStorage.getItem(DASHBOARD_PREVIEW_STORAGE_KEY) === "1";
}

function subscribeDashboardPreview(onStoreChange: () => void): () => void {
  if (typeof window === "undefined") return () => {};

  window.addEventListener("storage", onStoreChange);
  window.addEventListener("popstate", onStoreChange);
  return () => {
    window.removeEventListener("storage", onStoreChange);
    window.removeEventListener("popstate", onStoreChange);
  };
}

export function useDashboardPreviewEnabled(): boolean {
  const enabled = useSyncExternalStore(subscribeDashboardPreview, readDashboardPreviewEnabled, () => false);

  useEffect(() => {
    if (process.env.NODE_ENV !== "development") return;
    const queryValue = new URLSearchParams(window.location.search).get("dashboard_preview");
    if (queryValue === "1") {
      window.localStorage.setItem(DASHBOARD_PREVIEW_STORAGE_KEY, "1");
    } else if (queryValue === "0") {
      window.localStorage.removeItem(DASHBOARD_PREVIEW_STORAGE_KEY);
    }
  }, []);

  return enabled;
}
