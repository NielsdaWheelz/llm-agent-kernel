# adr 0011: make the native tool ceiling a host prerequisite

status: accepted, 2026-10-02; installed qualification in progress.

stock 0.160.0 model metadata overrides feature-off defaults: native CodeMode,
clock and async user-input can execute despite those flags. ordinary v2 events
hide CodeMode wrappers. a successful strict-json callback turn and zero typed
authority events therefore cannot establish containment.

use the public host-start `model_catalog_json` configuration with a pinned complete
vendor catalogue, restricted only to direct calls and removal of inherited clock
and async user-input selectors. preserve exact model, account, effort and remaining
metadata. per-thread catalogue overrides are documented no-ops and are forbidden.
provider-runtime owns the restricted catalogue artifact/materialization and
protocol prerequisite checks; applications never copy its compiler or data.

nexus already owns a dedicated native service. the owner selected a separate
contained jarvis endpoint instead of changing its shared coding server. host
operations owns that additional service, account state and socket publication;
the kernel owns none. native process/callback authority is never widened to make
the integration work.

stock sockets use a private physical `/tmp/codex-daemon-uid` root. cross-uid
jarvis access must isolate that root in the native service's mount namespace,
share only its owned socket directory and empty cognition directories, and
publish a relative socket alias. no callback relay or change to the unrelated
global coding socket directory is permitted. qualify actual uid/group access,
source/catalogue policy and direct callbacks together.

costs: one additional jarvis service; a fixed vendor catalogue loses automatic
model discovery and needs explicit update/requalification. direct tool mode also
removes vendor CodeMode convenience, clock and native user-input on that endpoint.
other coding endpoints retain their behavior. this is configuration of the stock
server, not a fork, a different model or an application executor.
