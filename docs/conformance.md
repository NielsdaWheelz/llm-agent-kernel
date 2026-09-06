# Conformance map

`Deterministic` means ordinary, network-disabled CI evidence. `Contract` means a
static/API or documentation proof. `Consumer qualification` and `Paid live`
identify obligations that this process-local library suite cannot honestly
claim to prove.

| Acceptance | Status | Primary evidence or remaining qualification |
| --- | --- | --- |
| K001 | Deterministic | `test_slice0_package.py::test_package_metadata_locks_qualified_git_dependencies`; `test_import_has_no_filesystem_or_network_side_effect` |
| K002 | Deterministic | `test_slice0_package.py::test_package_metadata_locks_qualified_git_dependencies` checks both exact immutable git revisions and `openai-codex==0.144.4`; `uv.lock` locks the matching SDK/runtime pair. `test_slice0_contracts.py::test_dependency_provider_event_contracts_are_exact`, `test_dependency_web_search_operation_deadline_api_is_revisioned`, `test_dependency_web_read_revision_refreezes_exact_host_table_plan`, and `test_dependency_web_read_v2_extraction_locators_are_exact` exercise the exact public provider and Web APIs and identities. |
| K003 | Deterministic | `test_slice0_contracts.py::test_dependency_pure_validation_and_host_table_publication`; `test_dependency_rejects_cross_catalog_implementation_substitution`; `test_dependency_web_search_operation_deadline_api_is_revisioned`; `test_dependency_web_read_revision_refreezes_exact_host_table_plan`; `test_dependency_web_read_v2_extraction_locators_are_exact`; `test_tools.py::test_redispatchable_write_timeout_requires_host_reconciliation_before_retry` |
| K004 | Deterministic | `test_tools.py::test_tool_validation_is_pure_strict_and_uses_the_plan_owned_binding`; `test_protocol.py::test_invalid_tool_input_is_one_protocol_failure_before_dispatch` |
| K005 | Deterministic | `test_slice0_package.py::test_runtime_uses_no_private_dependency_imports`; `test_kernel_does_not_reimplement_llm_tools_owners` |
| K006 | Deterministic | `test_slice0_package.py::test_package_contains_no_application_infrastructure` |
| K007 | Contract + consumer qualification | The fakes identify themselves as process-local test doubles; `docs/host-integration.md` enumerates the durable host facts. A real consumer must qualify its stores. |
| K008 | Deterministic | `test_slice0_package.py::test_production_never_calls_event_discarding_run_turn_projection`; `test_provider.py::test_observed_turn_uses_latest_snapshot_terminal_precedence_and_one_add_per_turn`; `test_kernel.py::test_commentary_agent_text_never_reaches_logical_validation_or_dispatch` |
| K009 | Deterministic | `test_protocol.py::test_conversational_provider_schema_is_one_closed_required_object`; `test_structured_provider_schema_requires_optional_and_nested_fields`; `test_provider.py::test_exact_request_mapping_private_cwd_cache_and_shutdown`; `test_kernel.py::test_whole_step_repair_is_effect_free_and_bounded` |
| K010 | Deterministic | `test_provider.py::test_exact_request_mapping_private_cwd_cache_and_shutdown` checks the complete request and private cwd posture. |
| K011 | Deterministic | `test_provider.py::test_exact_request_mapping_private_cwd_cache_and_shutdown` checks the pinned sentinel while `test_tools.py::test_host_plan_proof_precedes_exact_dependency_publication` proves application authority comes from the plan. |
| K012 | Deterministic | `test_provider.py::test_native_authority_event_discards_without_returning_terminal`; `test_kernel.py::test_native_authority_event_fail_stops_without_host_action` |
| K013 | Deterministic | `test_provider.py::test_observed_turn_uses_latest_snapshot_terminal_precedence_and_one_add_per_turn`; `test_observed_turn_uses_latest_progressive_snapshot_when_terminal_usage_is_absent`; `test_resumed_session_charges_only_invocation_local_usage`; `test_missing_later_turn_usage_makes_the_run_total_unavailable`; `test_typed_non_success_terminal_is_preserved_and_session_is_closed`; `test_kernel.py::test_commentary_agent_text_never_reaches_logical_validation_or_dispatch`; `test_six_turn_resumed_session_settles_invocation_local_usage_once_per_turn` |
| K014 | Deterministic | `test_provider.py::test_exact_request_mapping_private_cwd_cache_and_shutdown`; `test_typed_non_success_terminal_is_preserved_and_session_is_closed`; `test_isolated_session_is_never_cached` |
| K015 | Deterministic | `test_provider.py::test_resume_incompatibility_gets_exactly_one_cold_open`; `test_runtime_error_kinds_remain_distinct_and_close_the_session`; `test_sessions.py::test_successful_terminal_disables_cold_fallback_before_step_action`; `test_kernel.py::test_provider_stop_kinds_consume_without_automatic_retry` |
| K016 | Contract | Public construction is exercised throughout `test_slice0_contracts.py`; `test_thread_dispatch_lineage_is_complete_and_immutable` specifically distinguishes and freezes claim/checkpoint/input/model-step identity, while `test_initial_read_public_api_and_isolated_positions_are_exact` covers the initial-Read value and isolated lineage domains. |
| K017 | Deterministic | `test_slice0_contracts.py::test_definition_is_frozen_and_fingerprint_covers_provider_configuration`; `test_input_projection_policy_is_validated_and_every_value_rotates_fingerprint`; `test_session_compatibility_revision_is_required_and_rotates_the_fingerprint`; `test_kernel_limits_are_finite_and_bounded`; `test_structured_output_requires_a_closed_object`; `test_protocol.py::test_unrepresentable_result_contracts_fail_during_construction` |
| K018 | Deterministic | `test_slice0_contracts.py::test_definition_is_frozen_and_fingerprint_covers_provider_configuration`; `test_structured_wire_compilation_has_a_deterministic_definition_fingerprint`; `test_definition_fingerprint_rotates_for_every_configurable_session_scope`; `test_input_projection_policy_is_validated_and_every_value_rotates_fingerprint`; `test_session_compatibility_revision_is_required_and_rotates_the_fingerprint`; `test_provider_configuration_rejects_authority_widening`; `test_sessions.py::test_session_compatibility_revision_rotates_saved_session_key` |
| K019 | Deterministic | `test_slice0_contracts.py::test_entry_points_require_the_exported_plan_aware_budget_factory`; `test_tools.py::test_host_plan_proof_precedes_exact_dependency_publication`; `test_cross_catalog_handler_implementation_substitution_fails_freeze_and_proof`; `test_cross_catalog_authority_substitution_never_reaches_a_kernel_run`; `test_kernel.py::test_frozen_plan_is_rejected_before_rendering_admission_or_provider`; `test_claimed_plan_constructs_and_verifies_its_own_tool_budget_before_io`; `test_mismatched_claimed_plan_budget_parks_before_rendering_or_io`; `test_initial_read_precedes_provider_and_shares_budget_with_model_calls` |
| K020 | Deterministic | `test_slice0_contracts.py::test_claim_and_append_batches_are_non_empty`; `test_kernel.py::test_no_work_and_deferred_admission_call_no_provider`; structural scan in `test_slice0_package.py::test_package_contains_no_application_infrastructure` |
| K021 | Deterministic | `test_slice0_fakes.py::test_session_ref_fake_enforces_generation_cas`; `test_sessions.py::test_successful_terminals_advance_ref_by_generation_cas`; `test_kernel.py::test_stale_session_cas_permits_no_dispatch_or_settlement` |
| K022 | Deterministic | `test_kernel.py::test_thread_streams_stores_ref_then_settles_valid_say`; `test_sessions.py::test_recovery_discards_speculative_ref_before_opening_provider`; `test_discard_before_replay_removes_advanced_ref_then_live_session` |
| K023 | Deterministic library seam + consumer qualification | `test_context.py::test_bootstrap_contains_stable_canonical_input_time_and_exact_host_table`; `test_default_input_projection_is_byte_for_byte_legacy_rendering`; `test_healthy_run_context_sends_dynamic_material_without_repeating_stable_context`; `test_new_context_counter_excludes_provider_material_and_output_schema`; `test_composed_conformance.py::test_suspension_resolution_cold_bootstraps_from_host_evidence`. The consumer must prove its supplied canonical history/action projection is durable and complete. |
| K024 | Deterministic library seam | `test_context.py::test_definition_can_hide_all_model_visible_input_timestamps`; `test_batch_as_of_on_request_does_not_expose_source_timestamps`; `test_unauthorized_batch_as_of_projection_is_rejected_before_rendering`; `test_appended_input_requires_one_aware_as_of_and_preserves_identity`; `test_tool_only_continuation_gets_no_repeated_input_or_ambient_clock`; `test_kernel.py::test_unauthorized_projection_is_rejected_before_claim_rendering_admission_or_io`; `test_thread_projection_applies_to_claim_and_appended_input_batches`; `test_restricted_projection_survives_resume_failure_cold_reconstruction`. Locale/timezone relevance is host-supplied context, not inferred by the kernel. |
| K025 | Deterministic | `test_protocol.py::test_conversational_provider_schema_is_one_closed_required_object`; `test_provider_envelope_decodes_conversation_and_tool_arguments_to_logical_steps`; `test_provider_envelope_rejects_malformed_branches_and_argument_strings`; `test_call_tool_forbids_model_authored_host_authority_metadata`; `test_conversational_validation_rejects_empty_mixed_unknown_and_extra_values` |
| K026 | Deterministic | `test_protocol.py::test_structured_provider_schema_requires_optional_and_nested_fields`; `test_empty_structured_result_is_explicitly_closed_and_required`; `test_provider_envelope_decodes_structured_nested_optional_result`; `test_structured_validation_forbids_say_and_strictly_validates_result` |
| K027 | Deterministic | `test_protocol.py::test_provider_tool_envelope_is_rejected_against_an_empty_plan`; `test_call_tool_resolves_exact_binding_and_purely_decodes_owned_input`; `test_invalid_tool_input_is_one_protocol_failure_before_dispatch`; `test_kernel.py::test_whole_step_repair_is_effect_free_and_bounded`; `test_frozen_plan_is_rejected_before_rendering_admission_or_provider` |
| K028 | Deterministic | `test_kernel.py::test_whole_step_repair_is_effect_free_and_bounded`; `test_protocol_poison_is_consumed_without_rearm`; `test_composed_conformance.py::test_poison_input_is_consumed_and_next_scan_finds_no_work` |
| K029 | Deterministic | `test_tools.py::test_plan_must_be_host_exposed_and_strictly_serial`; `test_kernel.py::test_serial_dispatch_lineage_includes_mid_loop_input`; `test_initial_read_precedes_provider_and_shares_budget_with_model_calls`; `test_initial_read_commentary_call_is_non_executable_and_usage_settles` |
| K030 | Deterministic | `test_slice0_contracts.py::test_kernel_limits_are_finite_and_bounded`; `test_dependency_web_search_operation_deadline_api_is_revisioned`; `test_kernel.py::test_cooperative_limit_stops_before_a_provider_turn`; `test_cooperative_limit_does_not_wrap_write_dispatch`; `test_reported_token_limit_stops_after_cas_before_model_action`; `test_turn_limit_consumes_after_the_reserved_turn`; dependency budget ownership is exercised by `test_tools.py::test_redispatchable_write_timeout_requires_host_reconciliation_before_retry`. |
| K031 | Contract + consumer qualification | `test_slice0_contracts.py::test_thread_dispatch_lineage_is_complete_and_immutable`; `test_kernel.py::test_pre_dispatch_append_revalidates_before_any_tool_action`; dependency effect-ID equality is exercised in `test_tools.py::test_redispatchable_write_timeout_requires_host_reconciliation_before_retry`. The host must crash-qualify durable action creation and stable position/effect identity. |
| K032 | Deterministic | `test_composed_conformance.py::test_discarded_billed_once_read_can_dispatch_again`; `test_slice0_contracts.py::test_initial_read_public_api_and_isolated_positions_are_exact`; `test_kernel.py::test_initial_read_precedes_provider_and_shares_budget_with_model_calls` |
| K033 | Deterministic | `test_kernel.py::test_suspension_is_durably_settled_and_returns`; `test_dispatch_and_checkpoint_defects_park_without_fabricated_success`; `test_tools.py::test_redispatchable_write_timeout_requires_host_reconciliation_before_retry` |
| K034 | Deterministic library seam + consumer qualification | `test_kernel.py::test_suspension_is_durably_settled_and_returns`; `test_composed_conformance.py::test_suspension_resolution_cold_bootstraps_from_host_evidence`. Durable resolution storage and evidence safety remain host qualifications. |
| K035 | Deterministic | `test_context.py::test_old_recomputable_read_is_replaced_by_explicit_reference_preserving_marker`; `test_read_without_a_stable_source_reference_is_not_omittable`; `test_write_and_required_context_are_never_silently_truncated`; `test_cumulative_bound_accounts_for_material_sent_on_prior_turns`; `test_new_context_counter_excludes_provider_material_and_output_schema`; `test_kernel.py::test_declared_initial_read_failure_is_a_typed_first_turn_observation`; `test_initial_read_budget_boundary_is_rendered_without_external_work`; `test_initial_read_observation_context_limit_stops_before_provider` |
| K036 | Deterministic | `test_protocol.py::test_conversational_validation_rejects_empty_mixed_unknown_and_extra_values` rejects the progress variant; streamed text suppression is covered by `test_provider.py::test_observed_turn_uses_latest_snapshot_terminal_precedence_and_one_add_per_turn` and `test_kernel.py::test_commentary_agent_text_never_reaches_logical_validation_or_dispatch`. |
| K037 | Deterministic seam + consumer qualification | `test_slice0_contracts.py::test_claim_and_append_batches_are_non_empty`; `test_slice0_fakes.py::test_empty_checkpoint_fake_does_not_invent_work`; `test_kernel.py::test_no_work_and_deferred_admission_call_no_provider`. Exclusive production claim ownership must be qualified in the host checkpoint store. |
| K038 | Deterministic | `test_kernel.py::test_serial_dispatch_lineage_includes_mid_loop_input`; `test_pre_dispatch_append_revalidates_before_any_tool_action`; `test_append_at_final_check_retains_paid_answer_for_old_checkpoint` |
| K039 | Deterministic | `test_slice0_fakes.py::test_cancellation_token_matches_provider_and_tool_shapes`; `test_kernel.py::test_preempt_releases_without_settlement_or_automatic_rearm`; `test_preempt_while_stopping_discards_one_speculative_generation`; `test_isolated_cancellation_before_dispatch_closes_without_tool_action`; `test_cancelled_before_provider_consumes_only_under_declared_rule`; `test_initial_read_cancellation_before_dispatch_and_after_completion` |
| K040 | Deterministic seam + consumer qualification | `test_kernel.py::test_append_at_final_check_retains_paid_answer_for_old_checkpoint` proves the finalization race contract. Atomic, idempotent durable settlement must be proven by the consumer checkpoint implementation. |
| K041 | Deterministic seam + consumer qualification | `test_kernel.py::test_preempt_releases_without_settlement_or_automatic_rearm`; `test_composed_conformance.py::test_poison_input_is_consumed_and_next_scan_finds_no_work`. Production startup scanning remains a host qualification. |
| K042 | Deterministic | `test_kernel.py::test_protocol_poison_is_consumed_without_rearm`; `test_reported_token_limit_stops_after_cas_before_model_action`; `test_provider_stop_kinds_consume_without_automatic_retry`; `test_turn_limit_consumes_after_the_reserved_turn`; `test_cancelled_before_provider_consumes_only_under_declared_rule` |
| K043 | Deterministic seam + consumer qualification | `test_slice0_fakes.py::test_admission_clean_exit_refunds_unused_capacity`; `test_admission_orphan_recovery_retains_capacity_charge`; `test_serial_child_shares_root_slot_and_charges_parent_reservation`; `test_kernel.py::test_six_turn_resumed_session_settles_invocation_local_usage_once_per_turn`; `test_absent_invocation_usage_retains_full_admission_token_reservation`; `test_reported_token_limit_stops_after_cas_before_model_action`; `test_child_one_shot_rejects_a_forged_independent_slot_before_provider`; `test_initial_read_commentary_call_is_non_executable_and_usage_settles`. The host must crash-qualify its durable admission journal and its finite route-specific token-overshoot allowance. |
| K044 | Deterministic seam + consumer qualification | `test_slice0_fakes.py::test_admission_rejects_attempt_beyond_durable_ceiling_without_reservation`; `test_kernel.py::test_attempt_ceiling_stops_before_admission_or_provider`; `test_claim_reservation_and_release_defects_never_reach_provider`; `test_composed_conformance.py::test_orphan_recovery_keeps_capacity_charge_and_allows_attempt_two`. Durable attempt counting and circuit-breaker operation remain host qualifications. |
| K045 | Contract + consumer qualification | The async port boundary and `docs/host-integration.md` prohibit transactions/row locks across I/O; `test_kernel.py::test_append_at_final_check_retains_paid_answer_for_old_checkpoint` proves later-run signalling semantics. Transaction-scope inspection belongs to each consumer adapter. |
| K046 | Deterministic | Existing one-shot evidence: `test_kernel.py::test_isolated_structured_run_is_fresh_closed_and_uses_no_saved_state`; `test_isolated_empty_plan_honors_restricted_input_projection`; `test_unauthorized_one_shot_projection_precedes_rendering_admission_and_provider`; `test_isolated_write_plan_is_rejected_before_admission_or_provider`; `test_isolated_budget_mismatch_is_rejected_before_admission_or_provider`; `test_isolated_admission_rejection_returns_without_provider_io`; `test_child_one_shot_rejects_a_forged_independent_slot_before_provider`. Initial-Read evidence: `test_one_shot_without_initial_read_is_exactly_unchanged`; `test_initial_read_precedes_provider_and_shares_budget_with_model_calls`; `test_declared_initial_read_failure_is_a_typed_first_turn_observation`; `test_initial_read_rejects_non_read_effects_before_io`; `test_invalid_initial_read_fails_before_admission_tool_or_provider_io`; `test_initial_read_tool_in_maximum_but_not_selected_plan_is_ungranted`; `test_stale_initial_read_plan_fails_before_any_external_boundary`; `test_initial_read_admission_and_budget_failures_precede_dispatch`; `test_initial_read_budget_boundary_is_rendered_without_external_work`; `test_initial_read_cancellation_before_dispatch_and_after_completion`; `test_initial_read_observation_context_limit_stops_before_provider`; `test_initial_read_dispatch_defects_settle_admission_and_open_no_provider`; `test_initial_read_commentary_call_is_non_executable_and_usage_settles`. |
| K047 | Deterministic | `test_provider.py::test_isolated_session_is_never_cached`; `test_kernel.py::test_isolated_structured_run_is_fresh_closed_and_uses_no_saved_state`; `test_isolated_provider_failure_closes_and_returns_typed_stop`; `test_isolated_cancellation_before_dispatch_closes_without_tool_action`; initial-Read tests assert provider open/close absence or completion at every pre-provider boundary. |
| K048 | Deterministic | `test_slice0_fakes.py::test_default_events_reject_private_fields_and_sink_failure_is_nonfatal`; `test_events.py::test_diagnostic_redactor_and_sink_failures_are_nonfatal`; `test_kernel.py::test_diagnostic_transcript_is_opt_in_and_redacted_before_sink`; `test_bounded_event_rejection_never_changes_one_shot_work` |
| K049 | Contract | `docs/host-integration.md` explicitly states both third-party transcript and deletion limitations. |
| K050 | Deterministic library injection + consumer qualification | `test_kernel.py::test_claim_reservation_and_release_defects_never_reach_provider`; `test_mismatched_claimed_plan_budget_parks_before_rendering_or_io`; `test_checkpoint_boundary_rejects_unknown_closed_results`; `test_stale_session_cas_permits_no_dispatch_or_settlement`; `test_dispatch_and_checkpoint_defects_park_without_fabricated_success`; `test_usage_settlement_defect_is_not_hidden_after_canonical_conclusion`; `test_initial_read_dispatch_defects_settle_admission_and_open_no_provider`; `tests/test_sessions.py::test_unknown_session_ref_results_fail_closed_before_semantic_action`; provider terminal/native failures and suspension are separately injected. Recorder/effect-commit and durable-store process-death injection must be repeated against the consumer implementations. |
| K051 | Deterministic library seam + consumer qualification | `test_composed_conformance.py` covers suspension/resolution, billed-once rerun, poison/no-rearm, orphan recovery/attempt two, finalization/follow-up, post-terminal preemption/recovery, appended steering followed by no-work, and an explicit three-claim progression through the attempt ceiling. Production durable-store process-death races remain consumer qualifications. |
| K052 | Deterministic contract + opt-in paid probes | `test_slice0_package.py::test_production_never_calls_event_discarding_run_turn_projection`; opt-in `tests/live/test_codex_qualification.py::test_live_codex_stream_continuation_and_cancellation`; `test_live_structured_nested_optional_output_and_commentary_selection`; `test_live_one_shot_uses_initial_read_before_first_provider_turn`; `test_live_json_encoded_tool_arguments`; `test_live_in_flight_cancellation`; `test_live_quota_exhaustion`. Provider compatibility qualification runs the first four plus in-flight cancellation against at least one currently supported local-account route. The current route is `gpt-5.6-terra`; retired `gpt-5.4` is not invoked through `local_account`. Continuation proves same-lease addition and close/reopen/resume without historical recharge; the structured probe submits the restricted projection with requested batch `as_of` and checks terminal selection when commentary is observed; the initial-Read probe proves a known typed observation is available to the first structured one-shot turn. Ordinary CI neither runs paid probes nor records private payloads; quota requires its additional gate and an already-exhausted profile. |

The dependency timeout test specifically proves that `Write` plus
`ReDispatchable` returns `RecoveryRequired` after timeout and remains blocked
until explicit host reconciliation supplies recovered-lease evidence. No
in-memory fake in this repository is evidence of crash durability.

The `llm-tools` propagation from kernel
`b53e4329d6a8fc8af622747c9670cf586cf9e1ff` qualifies dependency revision
`9e6d155f3b64f03495911435b7cae8b8d131f9a2` through the exact-pin package test,
public Web API and extraction canaries, the recomposed v2 `web.read` HostTable
publication, and the fetched dependency suite. The `web.read` implementation and
extraction locator identities rotate, while its contract and policy identities
and all `web-search-v2` identities remain unchanged. No kernel source,
`provider-runtime`, `openai-codex`, provider adapter, request containment, or
structured-output wire changes. The paid `gpt-5.6-terra` and `gpt-5.4`
qualification recorded for that unchanged provider surface was applicable to
that historical release. Current route requirements are governed by K052.

The historical provider-runtime usage propagation from kernel
`c9dac7a610636a668bbf932cc2f961c0904f9157` qualifies dependency revision
`f477dcdcad03c30019576203d4eb8a3581a6d32f` through the exact-pin package test,
the invocation-local public API canary, provider adapter regressions, and the
fetched dependency suite. Provider-runtime owns cumulative native-session
normalization. The unchanged kernel adapter selects the latest progressive
snapshot, prefers terminal usage, and adds one invocation-local value once per
turn; its lease total spans kernel turns but never resumed history. The six-turn
resumed-session integration settles within an exactly sized reservation, and
missing usage retains the token reservation. No kernel runtime, persistence,
session-reference, authority, containment, replay, recovery, provider request,
structured-output wire, `llm-tools`, or Codex SDK change is introduced; existing
native sessions remain compatible without a compatibility-revision rotation.

Paid release qualification on 2026-09-04 passed the conversational
continuation/close/reopen/resume accounting, nested nullable structured output,
and JSON-string tool-argument probes on both `gpt-5.6-terra` (3 passed) and
`gpt-5.4` (3 passed). The separately gated in-flight cancellation probe passed
on `gpt-5.6-terra`. A resumed terminal exercised the permitted `Absent` usage
case and the new lease remained incomplete rather than charging historical
tokens. No already-exhausted qualification profile was configured, so quota
exhaustion was not run and no account was deliberately exhausted.

The provider-runtime propagation from kernel
`09f08df2970121ababe973b0e92d6901dd40da9e` qualifies dependency revision
`2cfed97ee5b9b8eb11103b0575eb7f29de00a0bd` through the exact-pin package test,
the public event-contract canary, the terminal-only consumer regression, and
the fetched dependency suite. Provider-runtime owns authoritative assistant
message selection: the last completed Codex `final_answer` wins, the last
phase-unknown completion is the fallback, and commentary is never executable.
The unchanged kernel adapter neither concatenates nor selects `AgentText`; only
the independently validated terminal structured value can become a model step.
No kernel runtime, provider wire, authority, containment, usage, recovery,
persistence, session-reference, `llm-tools`, or Codex SDK change is introduced,
and existing native sessions remain compatible without a kernel compatibility
rotation.

Paid release qualification on 2026-09-05 passed the conversational
continuation/close/reopen/resume and invocation-local usage probe, the nested
nullable structured-output plus observed commentary/final-answer selection
probe, and the JSON-string tool-argument probe on the currently supported
`gpt-5.6-terra` local-account route (3 passed). The separately gated in-flight
cancellation probe also passed (1 passed). Retired `gpt-5.4` was not invoked.
No already-exhausted qualification profile was configured, so quota exhaustion
was not run and no account was deliberately exhausted.

The input-projection release from kernel
`670da13ff0cfe766f36d8966e0575db0f7525143` adds only kernel-owned immutable
projection values, definition fingerprint coverage, pre-boundary invocation
validation, and rendering selection. Default rendering is byte-for-byte stable;
the new policy can suppress per-input timestamps and controls batch `as_of` as
always, never, or explicitly requested. Operational input time remains intact.
The plan, HostTable, provider request/wire, strict output, authority,
containment, accounting, cancellation, recovery, persistence, session-reference
format, and all three immutable dependency pins are unchanged.

Paid release qualification on 2026-09-06 passed the conversational
continuation/close/reopen/resume and invocation-local usage probe, the restricted
input projection plus nested nullable structured-output and observed
commentary/final-answer selection probe, and the JSON-string tool-argument probe
on `gpt-5.6-terra` (3 passed). The separately gated in-flight cancellation probe
also passed (1 passed). Retired `gpt-5.4` was not invoked. No already-exhausted
qualification profile was supplied, so quota exhaustion was not run and no
account was deliberately exhausted.

The deterministic initial-Read release from kernel
`7f3a9b145e68ba23c8aafad08500e9c452a9faef` adds `InitialReadCall`, one optional
`run_one_shot` argument, initial/model isolated lineage positions, exact
preflight, normal serial dispatch, and first-turn typed observation projection.
No-prelude rendering and behavior remain exact. One plan-aware `BudgetState` is
shared across the initial and model-proposed calls, while `llm-tools` remains the
only owner of tool call, attempt, byte, external-attempt, and elapsed accounting.
No definition fingerprint input, continuing-session identity, provider request
or wire, thread path, persistence/session-reference format, dependency pin, or
authority/containment/replay/recovery policy changes.

Paid release qualification on 2026-09-06 passed continuation with
close/reopen/resume usage accounting, restricted nested/nullable structured
output with observed commentary/final-answer selection, the new kernel one-shot
initial-Read context probe, and JSON-string tool arguments on `gpt-5.6-terra`
(4 passed). The initial-Read probe proved a known completed Read observation was
present and usable in the first provider turn. The separately gated in-flight
cancellation probe also passed (1 passed). Retired `gpt-5.4` was not invoked.
No already-exhausted qualification profile was supplied, so quota exhaustion
was not run and no account was deliberately exhausted.
