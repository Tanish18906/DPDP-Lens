# Docs index (DPDP Lens, Hack-a-Sol 5.0)

AGENTS.md at the repo root is the rulebook for the coding agents (ask-first behaviour, setup, step order). These docs are the detail behind it. If a doc and AGENTS.md disagree, stop and ask the human.

| # | File | What it covers | Who reads it |
|---|------|----------------|--------------|
| 01 | 01-product-overview.md | Pitch, scope, MUST/SHOULD/STRETCH, judging map, market reality | everyone |
| 02 | 02-architecture.md | Components, data flow, ports, tech choices, folder layout | everyone |
| 03 | 03-data-contract-and-api.md | Scan JSON, check ids table, engine API | everyone |
| 04 | 04-legal-reference.md | Verified DPDP clauses, wording rules, what not to claim | everyone |
| 05 | 05-engine-build.md | Every scanner, recognizers, fix loop, tests | Tanish's agent |
| 06 | 06-testapp-build.md | TutorNest target app, DB schema, planted violations V1 to V8, tests | Tanish (V1 to V4), Anmol (rest) |
| 07 | 07-ui-ux.md | Users, flows, screens, copy, states | Anmol's agent |
| 08 | 08-design-system.md | Colours, type, spacing, components | Anmol's agent |
| 09 | 09-dashboard-build.md | Dashboard build spec and build order | Anmol's agent |
| 10 | 10-implementation-plan.md | Hour by hour plan, owners, cut line, sleep | everyone |
| 11 | 11-demo-and-submission.md | Demo script, deck, video, README, judge Q and A | everyone |
| 12 | threat-model.md | Threat model of the auditor itself (submission item) | Tanish |
| 13 | 13-work-split.md | Who are you question, T and A phases, gates, STATUS files | both agents, read right after AGENTS.md |

## What to tell each agent to read first
- Tanish's agent: AGENTS.md, then 01, 02, 03, 04, 05, 06, 10.
- Anmol's agent: AGENTS.md, then 01, 02, 03, 07, 08, 09, 06 (tests and V5 to V8 sections), 10.

## Rule for changing these docs
Small fixes are fine. Anything that changes the JSON contract (03) or the planted violations (06) must be agreed between Tanish and Anmol first.
