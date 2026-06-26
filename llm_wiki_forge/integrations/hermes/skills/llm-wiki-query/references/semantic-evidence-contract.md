# Semantic Evidence Contract

`semantic.intake` describes the question before routing.

- `question_type`: formula, dispatch rule, API flow, writeback, route map, payment, address/geocoding, impact, or unknown.
- `must_answer`: checklist the final answer should cover.
- `not_asking`: neighboring interpretations to avoid.
- `requires_code_evidence`: implementation claims require source evidence.
- `cross_repo_likely`: weak single-module evidence should broaden to the canonical roots.

`semantic.routing` describes routing confidence.

- `ambiguity=low`: proceed with planned files.
- `ambiguity=medium/high`: treat top module as provisional.
- `needs_fixed_matrix=true`: verify `TGDS.WebAPI`, `TGDS-Dispatch-WebAPI`, `DispatchRule`, and `CoreServers` before a negative answer.

`semantic.evidence_sufficiency` describes answer readiness.

- `strong`: direct evidence exists and is suitable for an answer.
- `partial`: evidence can guide source reading, but should not support a broad claim alone.
- `weak`: answer should not be synthesized; backfill, hardening, or fixed-matrix verification is needed.

The semantic contract is a control plane. It can tell the agent where to look and whether evidence is enough, but it is not proof by itself.
