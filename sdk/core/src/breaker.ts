/** Local circuit breaker, per SDK instance.
 *
 * During a sustained Varsten outage this stops the SDK from paying the Varsten
 * timeout on every request: after K consecutive Varsten-originated failures it
 * opens and the SDK skips Varsten entirely (goes straight to the provider) for a
 * jittered cooldown, then lets a single probe through. A probe success closes it;
 * a probe failure reopens it.
 *
 * Only Varsten-originated failures count. A relayed provider error is the
 * provider's problem and never trips this breaker.
 */
export class LocalBreaker {
  private failures = 0;
  private openedAt = 0;
  private cooldownWithJitter = 0;
  private halfOpen = false;

  constructor(
    private readonly threshold = 5,
    private readonly cooldownMs = 30_000,
    private readonly now: () => number = Date.now,
  ) {}

  /** Whether a request may attempt Varsten now. */
  allow(): boolean {
    if (this.openedAt === 0) return true;
    if (this.now() - this.openedAt >= this.cooldownWithJitter) {
      // Cooldown elapsed: let exactly one probe through (half-open).
      this.halfOpen = true;
      return true;
    }
    return false;
  }

  recordSuccess(): void {
    this.failures = 0;
    this.openedAt = 0;
    this.halfOpen = false;
  }

  recordVarstenFailure(): void {
    this.failures += 1;
    if (this.halfOpen || this.failures >= this.threshold) {
      this.open();
    }
  }

  private open(): void {
    this.openedAt = this.now();
    this.halfOpen = false;
    // +/-20% jitter so many instances do not all probe in lockstep.
    const jitter = this.cooldownMs * 0.2 * (Math.random() * 2 - 1);
    this.cooldownWithJitter = Math.max(0, this.cooldownMs + jitter);
  }

  /** Test/introspection helper. */
  get isOpen(): boolean {
    return this.openedAt !== 0 && this.now() - this.openedAt < this.cooldownWithJitter;
  }
}
