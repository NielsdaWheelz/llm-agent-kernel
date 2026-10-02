# composed answer bounds

status: design selected; implementation and qualification pending, 2026-10-02.

problem: jarvis validates answer/limitation/question fields separately, but their
combined rendering can exceed discord's 2,000-character limit. the current final
union also cannot express the selected pending-work outcome.

impact: valid individual fields can fail publication; confident terminal prose can
misrepresent waiting work.

evidence: jarvis terminal.py:50–109,185–242; definitions.py:219–236.
[selected content contract](../native-agent-spec.md#final-and-content-contract).

resolved when: validate the complete rendered message, preserve native evidence on
failure and emit the existing bounded host failure response. waiting presentation
and host-validated per-input disposition stay distinct. qualify n4/N019 with useful
partial answers, pending actions, long composed text and no silent action resolution.
