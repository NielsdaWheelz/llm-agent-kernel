# nexus metadata integration handoff

status: **NOT_READY** for implementation integration; implementation authorized
and underway, 2026-10-02. isolated `feature/native-agent-supervision` worktrees
exist; no qualified kernel/provider/tools pin set or adapter commit is ready.
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
| kernel checkout | `feature/native-agent-supervision`, `/Users/nnandal/Documents/code/llm-agent-kernel-native`; implementation underway |
| current declared provider pin | `69d41d38a3d290e7ae3bde9b57556dda41e1b2f1`; baseline, not the repair |
| current declared tools pin | `9e6d155f3b64f03495911435b7cae8b8d131f9a2`; baseline, not callback qualification |
| ready integration branch / new immutable pins | unavailable; candidate branches are unqualified |
| exact selected model/effort + strict-json + successful web search/read | actual personal `gpt-6-luna`/`xhigh` and strict json + declared echo callback green on 0.160.0; actual research pending separately |
| four-tool declaration, dispatch, result and scope proof | frozen declaration is present; live research underway, unqualified |
| controlled preflight/native-failure/cleanup/uncertainty fixtures | provider native 10/10 and kernel native 5/5 candidate green; real nexus postgres unresolved/local-stop/parent-terminal anomaly block redispatch |
| durable terminal -> forced product failure -> local recovery | candidate postgres green: exact own seal retained, cold local recovery and Completed replay with provider/catalog trap |

before marking ready, replace the unavailable row with fetchable commits for each
dependency and the nexus adapter branch; record clean installed lock resolution,
schema migration, installed native build, actual selected model/effort, acceptance
commands and results. successful live search/read must include real returned tool
results and valid final metadata. controlled provider failures are separate proof,
never a substitute for that successful live journey.

the metadata owner chooses its domain fixtures and expected metadata. the kernel
owner supplies adapter/capability evidence and does not edit the metadata worktree.

implementation progress is recorded in [evidence](../native-agent-evidence.md).
an inactive Uncertain journal remains blocked even if a parent terminal exists.
native terminal recovery must use the kernel-owned authoritative native receipt
and perform no provider call; metadata's Completed publication memo is separate.

the shared execution seam is `execute_generation`: it reads the stable journal
before catalog/provider work. on an Uncertain native generation it accepts only
that exact model attempt's independently committed provider seal (or authoritative
non-submission proof), then resolves product state locally. an early domain guard
must eventually defer to that qualified seam; parent outcomes remain irrelevant.
this describes candidate implementation, not permission to weaken metadata's guard
before installed integrated proof.

the adapter migration is `0254_native_agent.py`, standalone parent `0252`.
metadata's uncommitted `0253_metadata_operations.py` has the same parent. final
integration requires a single agreed chain; metadata's owner retains its migration
ownership. neither branch may publish a two-head deployment.
