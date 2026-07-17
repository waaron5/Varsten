# @varsten/core

Provider-agnostic fail-open primitives shared by Varsten's SDK wrappers.

> Status: v0.1.0 beta. Public API stability follows semantic versioning; review
> release notes before upgrading between beta versions.

This package contains the fallback decision engine, local circuit breaker, error
taxonomy, metadata helpers, URL helpers, and best-effort telemetry plumbing used
by `@varsten/openai`, `@varsten/anthropic`, and `@varsten/gemini`.

Most applications should install a provider wrapper instead of importing this
package directly.

## Install

```bash
npm install @varsten/core
```

## Runtime compatibility

`@varsten/core` is an ESM package for Node.js 18 or newer. It ships JavaScript,
TypeScript declarations, source maps, and declaration maps. CommonJS consumers
must use dynamic `import()` or an ESM entry point.

The package sends no telemetry on its own. Provider wrappers opt into the
best-effort fallback emitter, whose payload is allowlisted to operational
metadata and never contains prompts or completions.

## License

Apache-2.0.
