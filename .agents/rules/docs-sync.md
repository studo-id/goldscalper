# GoldScalper Documentation & Strategy Sync Directive

> **Scope:** Automatic rule for all agents, subagents, and tools working on GoldScalper.

## Mandatory Directives:

1. **Continuous Documentation Sync (Docs-First):**
   - Every time trading logic, risk thresholds, dynamic SL/TP behavior, lot sizing, circuit breakers, or UI telemetry change, the corresponding documentation in `docs/` MUST be updated immediately.
   - Core mapping:
     - Worklog & Progress History: `docs/PROGRESS.md` *(Mandatory: Add new entry at top for every feature/strategy change)*
     - FinEng, The Juggler, BizDev & Rebate logic: `docs/QUANT_FINENG_BIZDEV_SPEC.md`
     - Project Roadmap & Execution Status: `docs/IMPLEMENTATION_PLAN_JUGGLER_BIZDEV.md`
     - System Architecture, Ports & Docker: `docs/BLUEPRINT.md`
     - Multi-entry, Pyramiding & Basket Rescue: `docs/MULTI_ENTRY_RESCUE_SPEC.md`
     - Core PRD & Objectives: `docs/PRD.md`

2. **No Code/Docs Desynchronization:**
   - Never change default settings in `config/settings.py` or `.env.example` without reflecting the new values and rationale in the relevant specification docs.
   - When adding new endpoints, metrics, or telemetry structures, document them in `BLUEPRINT.md` and the relevant implementation plan.

3. **Status & Milestone Tracking:**
   - Always record completed tasks, live validations, and empirical results (e.g. log output, test runs) directly in `docs/PROGRESS.md` and implementation plans so future sessions have full context.
   - When deploying to server (`studo@100.114.150.48`), sync modified documentation files alongside python/frontend files.
