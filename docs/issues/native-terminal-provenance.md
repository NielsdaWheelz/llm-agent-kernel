# native terminal provenance

status: open; provider/consumer representation gap, 2026-10-02.

problem: `AgentTerminal` and nexus's terminal envelope include locally synthesized
timeout/cancel/backend failures without identifying whether native finality exists.
host admission timestamps are also distinct from native acceptance.

impact: consumers cannot infer native completion or safe retry from terminal type
or status. callback recovery would inherit a false certainty boundary.

evidence: [review finding 2](../native-agent-review.md#2-a-typed-terminal-does-not-establish-native-finality),
pinned provider `runtime.py:1231–1254`, `codex_sdk.py:746–760`,
`events.py:188–208`; nexus `host.py:1398–1462`.

resolved when: the public contract distinguishes native turn evidence, local
termination, submission uncertainty and cleanup; turn-scoped protocol validation
defines finality. lost transport after start cannot become invented native
completion. N004 and consumer adoption N008 must pass. migration must not assign
unsupported native provenance to old records. [exact evidence and raw output types](../native-agent-spec.md#5-terminal-truth-and-product-acceptance)
are selected; implementation and qualification remain. preserve claude's separately
supplied structured payload and optional result identity; do not invent either.
