# 04 Legal reference (verified clauses only)

Sources: DPDP Act 2023 (indiacode.nic.in a2023-22.pdf and the MeitY Act PDF) and DPDP Rules 2025 (MeitY Rules PDF, notified 13 to 14 Nov 2025, final). We read the English text. Not a lawyer. Do not cite anything not listed here.

## Act
- s5 notice before or at the time of asking for consent.
- s6(1) consent free, specific, informed, unambiguous, clear affirmative action. s6(4) withdrawal as easy as giving. s6(6) stop processing after withdrawal. s6(10) fiduciary must prove notice and consent.
- s8(1) fiduciary stays responsible even for its processors. s8(2) processors only under a valid contract. s8(5) reasonable security safeguards. s8(6) breach notice to the Board and each affected person. s8(7) erase when consent is withdrawn or purpose is served. s8(9) publish contact of DPO or another person. s8(10) grievance redressal mechanism.
- s9(1) verifiable parental consent for under 18. s9(3) no tracking, behavioural monitoring or targeted ads aimed at children. Child means under 18 (s2(f)).
- s2(u) personal data breach definition.
- s11 access, s12 correction and erasure, s13 grievance, s14 nomination (rights of the data principal).
- s17(3) the government MAY notify classes of fiduciaries, including startups, as exempt from s5, s8(3), s8(7), s10, s11. No such notification found. s8(5) is never exempted under s17(1).
- Penalty schedule: s8(5) up to Rs 250 crore. s8(6) and s9 up to Rs 200 crore. Other provisions up to Rs 50 crore.

## Rules
- Rule 3 notice: standalone, plain language, itemises personal data and specific purposes, gives links to withdraw consent, exercise rights and complain to the Board.
- Rule 6(1) safeguards: (a) encryption, obfuscation, masking or virtual tokens, (b) access control, (c) logs, monitoring and review, (d) backups and continuity, (e) retain logs and personal data 1 year, (f) processor contract security terms, (g) effective technical and organisational measures.
- Rule 7 breach: tell each affected person promptly (what happened, consequences, mitigation, protective steps, business contact). Tell the Board without delay and give a detailed report within 72 hours.
- Rule 8(3): keep personal data, traffic data and logs at least 1 year, then erase unless a law requires more.
- Rule 8(1) and 8(2): erasure after inactivity with 48 hours notice. Applies ONLY to e-commerce and social media with 2 crore or more users and online gaming with 50 lakh or more. Do NOT flag it for a small app.
- Rule 9 publish business contact prominently. Rule 14(1) publish how to make a rights request. Rule 14(3) publish the grievance process and respond within 90 days at most. Rule 14(4) nomination.
- Rule 10 verify the parent is an identifiable adult. Rule 12 and Fourth Schedule: some exemptions from s9(1) and s9(3). Educational institutions are exempt only for tracking and behavioural monitoring tied to educational activities or enrolled child safety. So our planted tracker is a marketing or ad pixel.

## Commencement
Rules 1, 2, 17 to 21 immediate. Rule 4 after 1 year (13 Nov 2026). Rules 3, 5 to 16, 22, 23 apply from 13 May 2027.

## Still unverified. Do not cite.
Online gaming erasure period, remaining Third Schedule rows, Seventh Schedule purposes, the last part of the Rules PDF.

## Wording rules for findings
- Say "likely does not meet" or "would not meet the safeguard expected by", not "violates" or "illegal".
- Always tie a finding to a clause AND to evidence. No clause without evidence.
- Say "readiness report", never "certified" or "compliant".
- When talking about penalties say "up to Rs 250 crore under the Act schedule", never "will be fined".
- Add an applicability note where relevant: "If this app is a notified startup class, s8(7) may be exempt. s8(5) still applies."

## Applicability profile (optional config)
A small config for the fiduciary type (startup, edtech, large e-commerce). It switches off checks that do not apply. Default profile: small edtech that handles minors.
