# ADR 0007: Park configuration defects atomically

- Status: Accepted
- Date: 2026-09-02

## Context

The v1 specification requires configuration defects to park canonical input and
trip a host circuit breaker. Returning a typed outcome after ordinary `release`
leaves a race in which startup scanning can reclaim the still-unconsumed input
before the caller records the park.

## Decision

`InputCheckpointPort` includes an idempotent `park` operation. It atomically
releases claim ownership into durable operator-only state and trips the
applicable circuit breaker before the kernel returns `configuration_error`.
Only explicit operator correction may make that input claimable again.

`release` remains non-scheduling cleanup for interruption and does not imply a
park. `settle` remains the only operation that stores a conclusion and consumes
input.

## Consequences

Production hosts must persist park and circuit-breaker state with claim
ownership. The in-memory fake demonstrates choreography but makes no durability
claim. This adds one narrow persistent host seam; it does not add a kernel
workflow, retry policy, queue, or application schema.
