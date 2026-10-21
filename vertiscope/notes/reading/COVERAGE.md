# Doc coverage ledger

Reading the `web_fiber_haptics` design corpus to ground `docs/THEORY.md`.

Status: `-` unread | `S` skimmed (headings + targeted grep) | `R` read in full |
`N/A` out of scope for the scrape/chunk/vectorize question (reason required)

**112 docs, 21,770 lines.** Read in full: 1,675 lines. Skimmed: 4,896. Out of scope: 787. **Unread: 14,412 lines.**

> Honest status: the algorithm-bearing docs are read; the bulk of the
> remaining corpus is frontend/editor surface. The one real gap is
> `ontological_warp.md` (2,091 lines, untriaged) plus the `code_specs/`
> and `code_architecture/` backend specs.

| st | lines | doc | finding |
|---|---|---|---|
| - | 629 | `docs/BLACK_SLATE_GOAL.md` | Frontend slate; companion to the dedup goal. Relevant only for the print grammar. |
| - | 67 | `docs/code_architecture/backend/agent.md` |  |
| - | 84 | `docs/code_architecture/backend/compute.md` |  |
| - | 74 | `docs/code_architecture/backend/layout.md` |  |
| - | 85 | `docs/code_architecture/backend/lifecycle.md` |  |
| - | 59 | `docs/code_architecture/backend/materialiser.md` |  |
| - | 67 | `docs/code_architecture/backend/persistence.md` |  |
| - | 34 | `docs/code_architecture/backend/README.md` |  |
| - | 78 | `docs/code_architecture/backend/retrieval.md` | High priority next. |
| - | 61 | `docs/code_architecture/backend/scanner.md` | High priority next. |
| - | 7 | `docs/code_architecture/backend.md` |  |
| - | 123 | `docs/code_architecture/contracts.md` |  |
| - | 198 | `docs/code_architecture/data_schemas.md` |  |
| - | 61 | `docs/code_architecture/frontend/cell.md` |  |
| - | 49 | `docs/code_architecture/frontend/imaginary.md` |  |
| - | 57 | `docs/code_architecture/frontend/membranes.md` |  |
| - | 57 | `docs/code_architecture/frontend/pulse.md` |  |
| - | 45 | `docs/code_architecture/frontend/README.md` |  |
| - | 58 | `docs/code_architecture/frontend/real.md` |  |
| - | 70 | `docs/code_architecture/frontend/spine.md` |  |
| - | 7 | `docs/code_architecture/frontend.md` |  |
| - | 70 | `docs/code_architecture/migration.md` |  |
| - | 119 | `docs/code_architecture/README.md` |  |
| - | 64 | `docs/code_architecture/subsystems.md` |  |
| - | 137 | `docs/code_constraints/api_routes.md` |  |
| - | 182 | `docs/code_constraints/backend_services.md` |  |
| - | 141 | `docs/code_constraints/env_scenarios.md` |  |
| - | 198 | `docs/code_constraints/frontend_rendering.md` |  |
| - | 160 | `docs/code_constraints/lifecycle_invariants.md` |  |
| - | 151 | `docs/code_constraints/persistence.md` |  |
| - | 158 | `docs/code_constraints/README.md` |  |
| - | 140 | `docs/code_constraints/repl_actions.md` |  |
| - | 106 | `docs/code_constraints/streaming.md` |  |
| - | 140 | `docs/code_constraints/ws_frames.md` |  |
| - | 83 | `docs/code_specs/backend/agent.md` |  |
| - | 91 | `docs/code_specs/backend/api.md` |  |
| - | 101 | `docs/code_specs/backend/compute.md` |  |
| - | 86 | `docs/code_specs/backend/layout.md` |  |
| - | 116 | `docs/code_specs/backend/lifecycle.md` |  |
| - | 64 | `docs/code_specs/backend/materialiser.md` |  |
| - | 89 | `docs/code_specs/backend/persistence.md` |  |
| - | 88 | `docs/code_specs/backend/retrieval.md` | Line-level retrieval spec — high priority next. |
| - | 66 | `docs/code_specs/backend/scanner.md` | Line-level scanner spec — **high priority next**. |
| - | 99 | `docs/code_specs/constants.md` |  |
| - | 61 | `docs/code_specs/errors.md` |  |
| - | 49 | `docs/code_specs/frontend/cell.md` |  |
| - | 54 | `docs/code_specs/frontend/imaginary.md` |  |
| - | 49 | `docs/code_specs/frontend/membranes.md` |  |
| - | 53 | `docs/code_specs/frontend/pulse.md` |  |
| - | 62 | `docs/code_specs/frontend/real.md` |  |
| - | 70 | `docs/code_specs/frontend/spine.md` |  |
| - | 75 | `docs/code_specs/README.md` |  |
| - | 89 | `docs/code_specs/repl.md` |  |
| - | 230 | `docs/code_specs/types.md` |  |
| - | 719 | `docs/CODEBASE_AUDIT_2026-06-08.md` | Audit of the discarded codebase; low value for the algorithm question. |
| S | 349 | `docs/DOC_MAP.md` | Navigation map; used to order this reading. |
| S | 2716 | `docs/DOMAIN_MODEL.md` | Grepped + read §1.2.1, §4.5, §4.6.1, §8D.20, §O.19, §O.22, §1650 type-detection. Regex-for-primitives / named-tree-for-structures; panel retrieval combiner. Full read pending. |
| N/A | 136 | `docs/EDITOR_INTEGRATION_ASSESSMENT.md` | Editor library choice. |
| - | 130 | `docs/features/6d_umap.md` |  |
| - | 153 | `docs/features/click_to_edit.md` |  |
| - | 150 | `docs/features/four_fixture_api.md` |  |
| - | 146 | `docs/features/halo_retrieval.md` |  |
| - | 139 | `docs/features/live_scan_cleanup.md` |  |
| - | 145 | `docs/features/pattern_map.md` | High priority next (pattern_map output panel). |
| - | 188 | `docs/features/README.md` |  |
| - | 125 | `docs/features/signal_stream.md` |  |
| - | 146 | `docs/features/three_register_model.md` |  |
| - | 124 | `docs/frontend/agent_and_rollout.md` |  |
| - | 93 | `docs/frontend/architecture.md` |  |
| - | 98 | `docs/frontend/billboard.md` |  |
| - | 96 | `docs/frontend/compile_collapse.md` |  |
| - | 121 | `docs/frontend/concept_view.md` |  |
| - | 121 | `docs/frontend/editor.md` |  |
| - | 143 | `docs/frontend/field_tree.md` |  |
| - | 137 | `docs/frontend/frame_bus.md` |  |
| - | 165 | `docs/frontend/gesture_gateway.md` |  |
| - | 100 | `docs/frontend/halo.md` |  |
| - | 87 | `docs/frontend/link_layer.md` |  |
| - | 100 | `docs/frontend/liveness.md` |  |
| - | 267 | `docs/frontend/object_exploration.md` |  |
| - | 115 | `docs/frontend/pattern_map_and_url_set.md` |  |
| - | 135 | `docs/frontend/projector.md` |  |
| - | 90 | `docs/frontend/README.md` |  |
| - | 126 | `docs/frontend/repl_mirroring.md` |  |
| - | 108 | `docs/frontend/retrieval_and_sidebar.md` |  |
| - | 109 | `docs/frontend/scan_streaming.md` | Delta frame contract; medium priority. |
| - | 192 | `docs/frontend/theme.md` |  |
| - | 129 | `docs/frontend/workspace_store.md` |  |
| N/A | 536 | `docs/FRONTEND_REDESIGN.md` | Frontend object model — out of scope for scrape/chunk/vectorize. |
| R | 262 | `docs/HTML_DEDUP_CONTENT_TREE_GOAL.md` | **Binding goal.** The output IS a dedup pure-text tree built from `fields`; token-set subsumption is authoritative, hash is pre-filter; rendered_text derives from it. Notes 02. |
| N/A | 115 | `docs/MILKDOWN_SLATE_GOAL.md` | Editor library choice. |
| R | 393 | `docs/MORTEGON_INTEGRATION_SCHEME.md` | Mostly 3D/2D interlock (out of scope). In scope: §1.1 fields as `<fwd-truncated-xpath>: <value>` + `↳` dedup-alias rows; §1.6/§7 syntax-agnostic recursive decomposition. |
| - | 171 | `docs/object_model/Agent.md` |  |
| - | 153 | `docs/object_model/ApparitionService.md` |  |
| R | 128 | `docs/object_model/ChunkPatternSchema.md` | **Schema/instance split.** Recursive `sub_patterns`, `accessor_map`, golden trio, persistent accessor table keyed (domain, pattern_hash). Notes 02. |
| - | 167 | `docs/object_model/ConceptEdge.md` |  |
| - | 153 | `docs/object_model/ConceptLifecycle.md` |  |
| - | 164 | `docs/object_model/ConceptNode.md` |  |
| - | 2 | `docs/object_model/ConceptualCompute.md` |  |
| - | 156 | `docs/object_model/Database.md` |  |
| - | 194 | `docs/object_model/Editor.md` |  |
| - | 2 | `docs/object_model/FieldTree.md` |  |
| - | 131 | `docs/object_model/Halo.md` |  |
| - | 136 | `docs/object_model/LayoutService.md` |  |
| - | 141 | `docs/object_model/PythonAPIMaterialiser.md` |  |
| - | 155 | `docs/object_model/README.md` |  |
| - | 157 | `docs/object_model/RolloutCoordinator.md` |  |
| - | 167 | `docs/object_model/UIStateService.md` |  |
| - | 163 | `docs/object_model/WebBrowser.md` |  |
| - | 2092 | `docs/ontological_warp.md` | 2091 lines, unexamined. **Largest unread doc** — must triage next. |
| R | 892 | `docs/REAL_TIME_SCAN_UPDATE.md` | **Primary source.** Delta-chunking algorithm, hash-diff transport, landmark anchoring, chunk ledger, bottom-up chunker, reference JS. Notes 01. |
| S | 1831 | `docs/USER_REQUIREMENTS_VERBATIM.md` | Grepped for §U/§V/regex/json. Heading format differs from my grep; §U golden example is quoted in full inside HTML_DEDUP_CONTENT_TREE_GOAL. Full read pending. |
