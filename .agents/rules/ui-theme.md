# GoldScalper UI Theme & Strict Borderless Directive

> **Scope:** Automatic workspace rule for all frontend and UI components in GoldScalper.

## Mandatory Rules:
1. **100% Borderless Everywhere:**
   - Never use 1px solid hairline borders on panels, cards, containers, buttons, pills, tooltips, or inputs.
   - Use `border: none;` consistently.
   - The only exception is single left border status indicators (`border-left: 3px solid ...`).

2. **Tonal Surfaces:**
   - Hierarchy is achieved solely through surface background steps: `var(--bg)` -> `var(--s1)` -> `var(--s2)` -> `var(--s3)`.
   - Never nest bordered cards.

3. **Accent & Typography:**
   - Active buttons/pills: `background: var(--accent); color: #0b0e14; font-weight: 700; border: none;`.
   - Fonts: `Plus Jakarta Sans` for UI copy, `JetBrains Mono` for tabular metrics and prices.
