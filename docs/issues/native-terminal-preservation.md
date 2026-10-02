# preserve terminal evidence through host failures

status: open; current provider/kernel/nexus failure paths, 2026-10-02.

problem: cleanup can prevent/overwrite terminal delivery. nexus also commits child
evidence in the transaction that performs product validation/encoding, so product
failure can erase a valid child result.

impact: known native outcomes become application uncertainty, obstructing local
repair and obscuring usage. treating every observed frame as valid would create
a different defect by weakening protocol validation.

evidence: [review findings 3–4](../native-agent-review.md#3-nexus-couples-provider-evidence-to-product-acceptance),
nexus `llm_execution.py:783–829`, `host.py:1032–1238`;
kernel `provider.py:243–265` and existing terminal-tail conformance.

reproduce during implementation: inject cleanup failure after a valid native
terminal; separately raise from nexus's product resolver/encoder, then restart.

resolved when: original valid evidence and usage survive both paths, product
processing can resume without provider I/O, invalid turn evidence cannot authorize
future effects, and simultaneous stop/terminal is truthful. N004 and N006–N008
cover provider/kernel n1 and nexus n2; callback delivery is not a prerequisite.
