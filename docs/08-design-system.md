# 08 Design system (dashboard)

Keep it small. One theme, dark, calm, serious. The goal is "security console that a judge trusts", not a flashy landing page.

## Colour tokens (CSS variables in dashboard/src/index.css)
    --bg:        #0B0F14   page background
    --panel:     #121821   cards and panels
    --panel-2:   #19212C   hover and selected rows
    --line:      #263140   borders
    --text:      #E6EDF3   main text
    --muted:     #8B98A8   secondary text
    --accent:    #3DDC97   primary action and verified (green)
    --critical:  #FF5C5C
    --high:      #FF9F43
    --medium:    #F5C451
    --low:       #6FA8DC
    --focus:     #7AA2F7

Verified or success uses --accent. Red is only for critical, failed and "not in the notice". Do not add more colours.

## Typography
- UI font: Inter (or system sans). Body 16px minimum, labels 14px, small captions 13px.
- Headings: 600 weight, 24px page title, 18px section titles.
- Monospace for evidence, diffs and clause refs: JetBrains Mono or ui-monospace, 14px.
- Score number: 56px bold.

## Spacing and shape
- 8px grid. Card padding 16 or 24. Gap between cards 16.
- Radius 10px for cards, 6px for chips and buttons.
- Borders 1px --line. No heavy shadows. A subtle shadow only on the detail panel.

## Components
- Severity pill: coloured dot plus uppercase label. Example: CRITICAL.
- Layer chip: small outlined chip (DB, CODE, API, BROWSER, NOTICE).
- Clause chip: monospace text like "Act s8(5)" with a tooltip of the note. Outlined, muted colour.
- Score gauge: half circle or ring, number in the centre, colour by band (below 50 red, 50 to 79 amber, 80 and above green).
- Findings row: severity pill, title, layer chip, first two clause chips, status.
- Evidence block: dark inset box, monospace, masked value highlighted.
- Diff viewer: monospace, green background tint for added lines, red tint for removed lines, line numbers optional.
- Badge: "Re-scan passed", "Tests passed", "Verified". Green with check if true, red with cross if false, grey if unknown.
- Buttons: primary (accent background, dark text), secondary (outlined). One primary action per area.
- Banner: top strip for engine errors and for cached mode.
- Progress steps: vertical list with a tick, spinner or dot.

## Layout
- Max content width 1280px, centred.
- Findings list left (about 40 percent), detail right (about 60 percent). Under 1000px wide, stack them.
- Sticky top bar.

## Motion
Only two animations: the score count up and the fix progress ticks. 200 to 400 ms ease out. Respect prefers-reduced-motion.

## Do not
- No gradients, glass effects, neon glows or emoji icons.
- No icon library needed. Use simple inline SVG for check, cross and warning.
- No dark red on dark background text (check contrast).

## Tailwind setup note
Use Tailwind with the tokens as CSS variables and extend the theme with these names. Keep the component styles in a few small React components, no CSS framework besides Tailwind.
