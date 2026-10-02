# nexus metadata integration handoff

status: **NOT_READY** for implementation integration; specification work only,
2026-10-02. no new qualified kernel/provider/tools pins or integration branch exist.
this is the coordination record for the metadata owner; do not infer readiness
from the accepted design or from controlled failure tests.

## ownership

- metadata: `/Users/nnandal/Documents/code/nexus-web-metadata`,
  `feature/metadata-enrichment`, base `a494f743`. owns metadata policy, schema,
  prompts, journal step selection and domain acceptance. this worktree is untouched.
- kernel stream: shared kernel, provider-runtime, llm-tools, nexus generation
  adapters, required integration migrations and dependency pins. metadata must
  not implement a local dispatch fix or another agent loop.
- integration stays through nexus `generation_service` and the existing durable
  generation/journal boundaries. no metadata import of provider internals.

## required capability

| field | exact requirement |
| --- | --- |
| route/account | codex personal; no api-route or account substitution |
| model/effort | `gpt-6-luna`, `xhigh`; retain actual resolved/wire identity as evidence |
| output | metadata's closed native structured-json schema; strict json decoding, no extracting json from prose or weakening the schema |
| runtime | 300-second generation bound; session-open/cleanup are separately reported |
| content | 32 kib = 32,768 bytes of content; preserve existing instructions/content distinction |
| context/output policy | 64,000 context tokens; 8,000 output tokens; preserve both in the frozen request |
| tools | actual `nexus.document.search`, `nexus.resource.read`, `web.search`, `web.read` under the admitted resource scope |
| identity | stable metadata journal step and generation identity; callback identity is subordinate, never a new logical job |
| recovery | commit native terminal before metadata decode/validation/publication; recover that work locally without another provider call |
| uncertainty | unresolved submission blocks redispatch of this metadata step; no timeout/exception/native-id absence proves non-submission |

the current `RequestBudget` describes prompt-context and reserved-output policy.
native enforcement of inner-loop context/output ceilings is **UNQUALIFIED**; a
frozen number or observed usage is not proof of enforcement. the provider review
must document exactly what the installed route supports before acceptance. do not
silently reinterpret either number, change reasoning, or substitute a model.

metadata's conservative uncertainty policy is explicit. jarvis's selected automatic
reasoning recovery does not authorize retrying an uncertain metadata step.
authoritative rejection before submission and a durable valid terminal are separate
states; neither is manufactured from a generic provider exception.

## delivery and readiness

the [native contract](../native-agent-spec.md#9-delivery-and-acceptance) assigns:

- n1: provider/kernel submission and terminal evidence.
- n2: nexus adapter/terminal-recovery repair on its current route, independently
  useful to metadata; current route acceptance does not qualify native callbacks.
- n3/n5: contained callback qualification and hard cutover of the replaced shell
  route. metadata domain code retains the generation-service seam.

| artifact/proof | current status |
| --- | --- |
| kernel checkout | `main`, `c5236809e3d8765b28e169792f50d24713c8a31a`; uncommitted design docs |
| current declared provider pin | `69d41d38a3d290e7ae3bde9b57556dda41e1b2f1`; baseline, not the repair |
| current declared tools pin | `9e6d155f3b64f03495911435b7cae8b8d131f9a2`; baseline, not callback qualification |
| ready integration branch / new immutable pins | unavailable |
| exact selected model/effort + strict-json + successful web search/read | `NOT_RUN` |
| four-tool declaration, dispatch, result and scope proof | `NOT_RUN` |
| controlled preflight/native-failure/cleanup/uncertainty fixtures | `NOT_RUN` for the target |
| durable terminal -> forced product failure -> local recovery | `NOT_RUN` for the target |

before marking ready, replace the unavailable row with fetchable commits for each
dependency and the nexus adapter branch; record clean installed lock resolution,
schema migration, installed native build, actual selected model/effort, acceptance
commands and results. successful live search/read must include real returned tool
results and valid final metadata. controlled provider failures are separate proof,
never a substitute for that successful live journey.

the metadata owner chooses its domain fixtures and expected metadata. the kernel
owner supplies adapter/capability evidence and does not edit the metadata worktree.
