# preserve effect ownership while deleting the shell route

status: design selected; implementation and qualification pending, 2026-10-02.

problem: nexus effect listing/undo joins generation_api_credentials for user
ownership. that table and its shell transport are deletion targets.

impact: deleting transport credentials first loses access to historical effects.

evidence: nexus services/agent_api.py:352–438; existing llm_tool_positions effect
receipts. [selected migration](../native-agent-spec.md#nexus-schema-and-composition).

resolved when: backfill immutable generation tool_principal_user_id, move existing
list/undo behavior to its transport-neutral owner, and qualify historical effect
authorization/undo before removing credential issuance/table/route. N020 owns proof;
historical transport labels remain audit only, never executable compatibility paths.
