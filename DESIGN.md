# Design notes

crowdtracker is a working tool (Impeccable's "Operate" mode): scanning and
updating come first, and the look serves that.

## Direction

- **Ink and paper chrome.** The top bar, buttons and selected states are a deep
  ink and a warm paper. No accent colour is spent on chrome.
- **Colour is data.** Platform colours say where a pledge lives. Amber means a
  date slipped; red means it is past due. Every coloured element also has a text
  label, so colour is never the only signal.
- **Signature: the slip track.** Every pledge is drawn on one shared time axis:
  a hollow ring for the promised date, a filled dot (in the platform's colour)
  for the latest estimate, an amber bar for the slip between them, a red bar
  from the estimate to today when overdue, and one "today" line running down
  the whole list.
- **The platform bar** above the list is both a breakdown (segment width =
  number of pledges) and the platform filter.

## Tokens

All in `frontend/src/styles.css`.

- Type: Hanken Grotesk (self-hosted via Fontsource), one family, fixed rem scale
  0.75 / 0.8125 / 0.9375 / 1.125 / 1.375. Tabular numerals on dates and counts.
- Neutrals and state colours are OKLCH custom properties with separate light and
  dark values (`prefers-color-scheme`).
- Platform colours live in the `.platform-*` classes. Kickstarter `#05CE78`,
  BackerKit `#FFD508` and Indiegogo (`#EB1478`, deepened to `#D6106B` so white
  text passes contrast) come from published brand values. **Gamefound,
  PledgeManager and PledgeBox are stand-ins**: none publishes a hex value I could find.

## Rules this UI follows

- Standard controls only: buttons, selects, inputs, a sortable table.
- Details open in a side panel (it takes over the screen on phones), not a modal.
- No eyebrow labels, gradient text, glass, side-stripe borders, emoji icons or
  nested cards.
- Motion is limited to 150 ms hover feedback and a 200 ms panel reveal, and is
  off under `prefers-reduced-motion`.
- Every view has loading, empty and error states.
