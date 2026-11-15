# adr 0013: explicit native authority and borrowed workspaces

- status: accepted by the jarvis slice 4 implementation request, 2026-11-15
- scope: native definitions and provider directory ownership; isolated roles stay contained
- consumer contract: jarvis `docs/private-notes-and-rolodex.md` under adr 0071

## decision

`ProviderConfiguration` carries `cwd: str | None = None` and
`additional_dirs: tuple[str, ...] = ()`. paths are normalized absolute paths;
a borrowed cwd cannot be `/`. `cwd_scope` is removed without an alias.
`cwd=None` retains an empty disposable directory. otherwise the kernel borrows
an existing readable/traversable directory and never creates, empties, chmods
or removes it. one private lease ownership fact controls cleanup, including
acquisition and close failures. native host write access is separately qualified;
application uid write access is not required.

`NativeDefinition` admits the explicit provider policy/native configuration.
provider-runtime owns exact supported-policy validation, effective thread settings,
native item identities and denied permission results. declared native tool
observations never enter the host callback journal. with built-ins enabled and
`approval=deny`, only a typed denied permission outcome is accepted; unexpected
or granted authority still fences the session. callback acceptance, actions,
original receipts and recovery are unchanged.

`AgentDefinition` requires `cwd=None`, no additional directories and the existing
complete containment policy/native options. `archive_internal` remains selectable.
no isolated role can borrow or widen its native authority.

both definition kinds use one internal provider identity encoding: configured
paths, complete policy/native options, model/catalog/auth selection and instructions.
generated disposable paths and mutable filesystem contents are excluded. native
base instruction v4 distinguishes native observations from durable callback
receipts and requires inspection before continuing interrupted native effects.

## costs and qualification

native tools inherit the selected host authority and have no host action ledger,
connector consent or automatic replay guarantee. a stop may leave detached work.
borrowed files and git history outlive provider sessions. no native process,
workspace service, shell wrapper or persistent session recovery is added.

this amendment supersedes disabled-native/workspace exclusions only for explicitly
declared native configurations. n014 and isolated-role containment remain binding
for disabled configurations. jarvis selects its exact workspace posture; the kernel
does not encode jarvis paths, git policy or role names. source/static and controlled
boundary proof are distinct from the consumer's stock-host candidate qualification.
