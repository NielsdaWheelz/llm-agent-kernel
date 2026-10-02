# review environment differs from declared provider pin

status: open local qualification issue, observed 2026-10-02.

problem: kernel `pyproject.toml` and `uv.lock` name provider `69d41d38…`, while the
existing `.venv` and sibling provider head are `4ddced3…`.

impact: focused kernel tests fail collection on missing `CodexCatalogSessionRequest`;
examining only the sibling head falsely reports newer public APIs missing.

evidence: installed distribution `direct_url.json`, git heads and exact-pin
source review; [validation record](../native-agent-review.md#review-disposition-and-validation).
58 tests passed with a temporary exact-pin source export. that is not an installed
package qualification and does not repair the shared environment.

resolved when: before implementation qualification, create an isolated environment
from the unchanged frozen lock, verify installed direct urls and run the relevant
checks there. do not change a dependency pin merely to match an old local install.
no production or deployed mismatch was inferred from this local observation.
