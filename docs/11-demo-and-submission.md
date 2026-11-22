# 11 Demo and submission

## Submission checklist (confirm exact items with the organisers)
- Public GitHub repo with README
- PDF deck
- 2 to 3 minute demo video
- Live link if applicable (ours runs locally, say so)
- Track extra: threat model (docs/threat-model.md)
- README declares AI tools (Claude Code, Antigravity) and credits every library and data file (Disconnect services.json, CC BY-NC-SA)
- Check the repo opens in a logged out browser

## README outline
1. Title and one line pitch
2. The problem (DPDP Act 2023, Rules 2025, duties from 13 May 2027)
3. What it does (4 layers, evidence plus clause, verified fix, notice vs runtime)
4. Screenshot or GIF of the dashboard
5. Architecture (short diagram from doc 02)
6. Quick start (3 commands to run the target app, the engine and the dashboard)
7. Checks table (from doc 03)
8. What it does not do (not a certificate, localhost only, limited checks)
9. AI tools used
10. Credits and licences
11. Team

## Deck outline (8 to 10 slides)
1. Title: DPDP Lens, "Does your app do what your privacy notice says?"
2. The deadline: DPDP duties start 13 May 2027, penalties up to Rs 250 crore for weak safeguards
3. The gap: tools check one layer, startups have no privacy team
4. Our approach: four layers, evidence, clause, verified fix
5. Live product: dashboard screenshot with score and findings
6. The verified fix: diff, re-scan, tests, score change
7. Notice vs Runtime: the headline insight
8. How it works: architecture, no heavy ML, runs on a laptop, deterministic
9. Limits and honesty: readiness report, not a certificate, what we did not verify
10. Roadmap: SARIF CI gate, more stacks, 72 hour breach report, applicability profiles
Keep 7 words per line or less. One idea per slide.

## Live demo script (2 minutes)
0:00 "This is TutorNest, a tutoring app for school students. It looks fine." Show the app for 5 seconds.
0:10 Click Run scan. Say: "We scan the database, the code, the running API and the browser."
0:25 Findings appear. Point at the score. "45 out of 100."
0:35 Click the critical finding. "A public endpoint returns Aadhaar and PAN with no login. Act section 8(5), Rule 6(1)(b). This is the evidence, masked."
0:55 Click Fix and verify. Watch the five steps.
1:15 Diff appears. "We patched a copy, restarted it, re-ran the check, and ran the app's own tests. Both pass."
1:30 Score goes up.
1:35 Switch to Notice vs Runtime. "The notice says name, email, phone. The app also handles date of birth, Aadhaar, parent PAN and sends data to a tracker. That gap is what a regulator would care about."
1:55 "Readiness report, not a certificate. Thank you."
Rehearse it three times. Time it.

## Demo safety
- Cached golden patch mode is ready and labelled.
- Cached scan JSON ready in case the engine fails.
- Target app and engine start commands saved in a script (run_demo.sh) that starts everything.
- Phone hotspot ready, though nothing needs the internet.
- Laptop charged, second laptop as backup, repo cloned on both.

## Video script
Same as the live demo with a voice over. Record at 1080p. Screen only plus voice. Keep under 3 minutes. Do a clean take after the freeze.

## Judge Q and A (prepare answers)
1. "Isn't this just a scanner?" It maps every finding to a clause with evidence and proves the fix by re-scan and tests. The verified fix is the difference.
2. "What about existing tools like Privado or dcomply?" They check one layer or manage consent workflows. We check four layers and compare the notice to what actually runs.
3. "Is this legal advice or a certificate?" No. It is a readiness report. We say so on every page.
4. "Does it work on other stacks?" The demo targets FastAPI and SQLite. The checks (API, DB, browser) are stack independent. Code rules start with Python. Roadmap covers more.
5. "How do you avoid false positives?" Context rules. Example: a 12 digit number is flagged as Aadhaar only with checksum and context. Evidence is always shown.
6. "What if the patch breaks the app?" The fix runs on a sandbox copy and the app's tests must pass before it is marked verified.
7. "Do you use an LLM?" Not required. Fixes are deterministic templates. An LLM may only explain.
8. "Does the auditor itself leak data?" Evidence is masked, nothing leaves the machine. See the threat model.
9. "Which clauses are you sure about?" We read the Act and Rules text. Anything we did not verify is not used.
10. "Does it apply to a small startup?" The Act lets the government exempt some startups from some sections, but security safeguards (s8(5)) stay. We have an applicability profile idea for this.
11. "The problem statement had only a title, how did you scope?" We read full-stack as database, code, API and browser, and said so up front.

## Presentation notes
Speak slowly. One person drives, the other handles questions. Both can explain every file. Admit limits first, it builds trust.
