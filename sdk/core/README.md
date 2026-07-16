# @varsten/core

Provider-agnostic fail-open primitives shared by Varsten's SDK wrappers.

This package contains the fallback decision engine, local circuit breaker, error
taxonomy, metadata helpers, URL helpers, and best-effort telemetry plumbing used
by `@varsten/openai`, `@varsten/anthropic`, and `@varsten/gemini`.

Most applications should install a provider wrapper instead of importing this
package directly.

## License

Apache-2.0.
