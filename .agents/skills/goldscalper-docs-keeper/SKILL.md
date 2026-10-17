---
name: goldscalper-docs-keeper
description: Automatically audits and synchronizes all GoldScalper project documentation (PRD, Blueprint, Quant FinEng/Juggler spec, and implementation plans) whenever code, trading strategy, or features change.
---

# GoldScalper Documentation Keeper Skill

## Purpose
Use this skill whenever:
- Adding, refactoring, or deleting any feature or trading logic.
- Adjusting risk parameters, SL/TP dynamics, lot sizing formulas, or timeouts.
- Adding API endpoints, database models, or telemetry fields.
- Re-aligning system architecture with live trading insights.

## The 6 Ground-Truth Documents
Keep these 6 core documents perpetually synchronized with `HEAD`:

1. **`docs/PROGRESS.md`**:
   - The master chronological worklog.
   - Every completed task, strategy shift, empirical finding, or bug fix MUST be prepended at the top with: date, title, phase, status, files touched, verification command, and next steps.

2. **`docs/QUANT_FINENG_BIZDEV_SPEC.md`**:
   - The Juggler (Financial Engineering & dynamic bleeding clamps: `1.1 * live_avg_win`).
   - BizDev Economics (Rebate extraction ~$6/lot, friction monitoring).
   - Dynamic SL/TP decision matrices based on live average win, equity progress, and hold duration.

3. **`docs/IMPLEMENTATION_PLAN_JUGGLER_BIZDEV.md`**:
   - Implementation task status (Phase 1 through 5).
   - Live validation logs, root-cause analyses, and empirical evidence.

4. **`docs/BLUEPRINT.md`**:
   - System architecture, Docker containers, ports, database schemas.
   - Component boundaries and companion document indices.

5. **`docs/MULTI_ENTRY_RESCUE_SPEC.md`**:
   - Multi-entry layering, pyramiding rules, and basket recovery break-even logic.

6. **`docs/PRD.md`**:
   - Product requirements, sprint yield goals (30%-40% daily on small capital).
   - Account setup and constraints.

## Synchronization Workflow
Whenever a change is proposed or executed:
1. **Identify Affected Docs**: Determine which of the 6 documents govern the code being touched.
2. **Prepend to `docs/PROGRESS.md`**: Record the work done, files changed, and test/verification output.
3. **Update Parameters**: Check `config/settings.py` and `.env.example` against tables in the docs.
4. **Record Progress**: Mark completed tasks in implementation plans.
5. **Deploy Mirror**: When deploying code to the server, ensure corresponding `docs/` files are deployed alongside code.
