/**
 * Per-request workflow metadata (D3 actionable support).
 *
 * This is how an application tells Varsten what a request IS — which feature,
 * which customer, which agent workflow step — so the engine can allocate cost,
 * plan task-aware optimizations, and detect redundant calls inside agent
 * traces. Serialized into the `X-Varsten-Metadata` header on the OPTIMIZED
 * attempt only: the direct provider fallback never receives it, because a
 * provider has no business seeing your workflow labels.
 *
 * Metadata only, never content: labels, ids, and levels. Do not put prompt or
 * completion text in these fields — Varsten's ledger is metadata-only and the
 * proxy treats these values as labels, not payload.
 */

import { randomUUID } from "node:crypto";

/** Header the Varsten proxy reads workflow metadata from. */
export const VARSTEN_METADATA_HEADER = "X-Varsten-Metadata";

/**
 * Workflow labels for one request. Field names are camelCase here and mapped
 * to the proxy's snake_case keys on serialization; anything in `extra` is
 * passed through as-is and preserved by the proxy under its bounded extra
 * keys (values must be short labels, never content).
 */
export interface VarstenRequestMetadata {
  /** Groups the calls of one logical workflow (an agent run, a session). The
   * engine's agent-loop detection finds redundant calls within a trace. */
  traceId?: string;
  /** The product feature this call serves (e.g. "support_agent"). Drives
   * allocation and per-route optimization decisions. */
  feature?: string;
  workflow?: string;
  /** YOUR customer behind this call — powers per-customer margin analysis. */
  customerId?: string;
  externalUserId?: string;
  userId?: string;
  team?: string;
  department?: string;
  environment?: string;
  /** Task classification hint (e.g. "classification.intent"). A confident,
   * low-risk task type unlocks more aggressive optimization candidates. */
  taskType?: string;
  riskLevel?: "low" | "medium" | "high";
  qualityThreshold?: string;
  /** Additional short labels; preserved by the proxy (bounded), never dropped. */
  extra?: Record<string, string | number | boolean>;
}

const FIELD_TO_KEY: ReadonlyArray<[keyof VarstenRequestMetadata, string]> = [
  ["traceId", "trace_id"],
  ["feature", "feature"],
  ["workflow", "workflow"],
  ["customerId", "customer_id"],
  ["externalUserId", "external_user_id"],
  ["userId", "user_id"],
  ["team", "team"],
  ["department", "department"],
  ["environment", "environment"],
  ["taskType", "task_type"],
  ["riskLevel", "risk_level"],
  ["qualityThreshold", "quality_threshold"],
];

/** Serialize metadata to the header value the proxy parses, or null when there
 * is nothing to send (no header beats an empty one). */
export function metadataHeaderValue(meta: VarstenRequestMetadata | undefined): string | null {
  if (!meta) return null;
  const out: Record<string, unknown> = {};
  for (const [field, key] of FIELD_TO_KEY) {
    const value = meta[field];
    if (value !== undefined && value !== null && value !== "") out[key] = value;
  }
  if (meta.extra) {
    for (const [key, value] of Object.entries(meta.extra)) {
      if (value !== undefined && value !== null) out[key] = value;
    }
  }
  return Object.keys(out).length > 0 ? JSON.stringify(out) : null;
}

/**
 * A trace groups one workflow's calls so the engine can see the workflow as a
 * whole — most importantly, find calls an agent repeats for nothing.
 *
 *     const trace = new VarstenTrace();
 *     for (const step of steps) {
 *       await client.chat.completions.create(body, {
 *         varsten: trace.metadata({ taskType: "research.step" }),
 *       });
 *     }
 *
 * Stateless beyond the id on purpose: no hidden counters, no global registry;
 * pass the trace where the workflow goes.
 */
export class VarstenTrace {
  readonly traceId: string;

  constructor(traceId?: string) {
    this.traceId = traceId ?? `trace-${randomUUID()}`;
  }

  /** Per-call metadata carrying this trace's id, merged over `meta`. */
  metadata(meta: VarstenRequestMetadata = {}): VarstenRequestMetadata {
    return { ...meta, traceId: this.traceId };
  }
}
