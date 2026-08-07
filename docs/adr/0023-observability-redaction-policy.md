# ADR-0023: Observability redaction policy

- **Status:** Accepted
- **Date:** 2026-08-07

## Context

RAG traces are valuable for debugging and evaluation but can themselves expose
document text, prompts, metadata, identities, model output, or restricted search
terms. Sending full traces to an observability backend would create a secondary
data-leak path.

## Decision

Use OpenTelemetry-compatible tracing and optional Langfuse integration behind a
redaction boundary. Telemetry is metadata-minimal by default.

Default traces contain safe identifiers, timings, counts, status/error classes,
profile/publication IDs, and hashes where appropriate—not raw document chunks,
prompts, answers, secret values, or sensitive metadata. Field classification and
redaction occur before export. Privileged content capture, if enabled for a
controlled diagnostic workflow, must be explicit, access-controlled, encrypted,
time-bounded, auditable, and disabled in the default/air-gapped profile.

## Consequences

Routine telemetry is safer but some debugging requires reproducing a request in
an authorized environment rather than inspecting raw traces.

## Verification

- Automated tests inject secrets/sensitive fields and confirm exporters receive
  redacted values only.
- Disabling external telemetry leaves local metrics/tracing functional.
- Observability failure cannot bypass application authorization or block core
  retrieval by default.
