# Security policy

Report vulnerabilities through GitHub's private security-advisory flow for this
repository. Do not include credentials, prompts, provider transcripts, tool
arguments, tool results, or other private payloads in a public issue.

Security fixes are made on the latest release line. Older release lines and
unreleased source snapshots are not supported.

The kernel does not make prompt injection harmless. Production hosts remain
responsible for durable canonical state, admission, credentials, policy,
effect recording and reconciliation, and delivery. Provider-native transcripts
are unredacted third-party data at rest; discarding a local session reference
does not promise provider deletion.

The definition-bound input projection can suppress kernel-rendered source
timestamps and batch `as_of` values, but it is not a general prompt redactor.
Hosts must not duplicate prohibited metadata in role, stable, retrieved, or
other caller-supplied prompt sections. Operational timestamps remain in host
memory/state even when omitted from model-visible context.

The exact `llm-tools` dependency pin uses `llm-tools-web-read-v2` extraction:
plain text is never interpreted as markup or entities, and HTML/XHTML parser
output is not entity-decoded a second time. Retrieved text remains untrusted;
these inert-extraction guarantees neither authorize disclosure to an external
destination nor turn retrieved instructions into trusted control data.
