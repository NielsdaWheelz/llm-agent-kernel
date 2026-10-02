# nested gate control during a native callback

status: open; control/ownership qualification required, 2026-10-02.

problem: jarvis's isolated write gate runs while the parent native turn awaits a
callback. the old serial child-slot assumption cannot describe this overlap.

impact: holding the provider reader in a callback can deadlock the gate;
incorrect ownership can permit an old callback to act after recovery.

evidence: [review finding 7](../native-agent-review.md#7-native-turns-invalidate-old-admission-arithmetic),
kernel [admission contract](../../SPEC.md#93-run-admission); jarvis
`admission.py:487–511` and `write_dispatch.py:202–210`.

the owner declined model usage limits and arbitrary jarvis task cutoffs. the old
hard/soft usage-budget question is resolved by [section 18](../../SPEC.md#18-native-agent-target-requirements),
not retained as an implementation gate.

resolved when: the nested gate can finish while its parent waits, under the same
current work owner and without a paid-capacity reservation or transport deadlock.
stop and ownership loss fence further dispatch while preserving action recovery.
N015 and jarvis N019 qualify this; usage is observational.
