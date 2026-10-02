# Assay: the RAG Foundry design system

Assay is the visual language for RAG Foundry's interface. Every claim shows its
source, and every governed object shows its review state. This folder holds the
design tokens and the Tailwind CSS v4 theme built from them.

| File | What it is |
|---|---|
| `tokens.json` | Source of truth. Every color, font, type size, radius and shadow. |
| `build_tokens.py` | Generates the two CSS files below and enforces contrast rules. |
| `tokens.css` | Generated. Every token as a `--rf-*` CSS custom property. |
| `tailwind.css` | Generated. A Tailwind v4 theme that maps utilities onto `--rf-*`. |

## Using it in the frontend

In the app's main stylesheet (Vite + Tailwind v4):

```css
@import 'tailwindcss';
@import '../design-system/tailwind.css';
```

Without Tailwind, import `tokens.css` and use the variables directly:
`background: var(--rf-surface); color: var(--rf-fg);`.

### Fonts

Deployments can be air-gapped, so serve fonts from the app bundle, not a CDN:

```bash
npm install @fontsource/ibm-plex-sans @fontsource/ibm-plex-mono @fontsource/source-serif-4
```

```ts
import '@fontsource/ibm-plex-sans/400.css';
import '@fontsource/ibm-plex-sans/500.css';
import '@fontsource/ibm-plex-sans/600.css';
import '@fontsource/ibm-plex-mono/400.css';
import '@fontsource/ibm-plex-mono/500.css';
import '@fontsource/source-serif-4/400.css';
import '@fontsource/source-serif-4/400-italic.css';
import '@fontsource/source-serif-4/600.css';
```

### Light and dark

Theme colors are defined with `light-dark()`, so they follow the operating
system by default. To force a theme, set `data-theme="light"` or
`data-theme="dark"` on `<html>` or on any subtree. Overrides can be nested and
the nearest one wins, for the colors and for the `dark:` variant alike. The
variant resolves up to three dark overrides stacked inside light ones (dark,
then light, then dark, and so on). Rendered document pages stay on paper, so
wrap the page canvas of the document viewer in `data-theme="light"`. Evidence
highlights and bounding boxes drawn over it then use their light values.

`light-dark()` needs Chrome or Edge 123, Firefox 120 or Safari 17.5 or later.

## Utilities

Tailwind's default palette, type sizes, radii and shadows are removed, so only
these exist:

- **Surfaces:** `bg-bg`, `bg-surface`, `bg-surface-raised`, `bg-surface-sunken`
- **Text:** `text-fg`, `text-fg-secondary`, `text-fg-muted`, `text-link`
- **Borders:** `border-border` (hairlines), `border-border-strong` (decorative),
  `border-border-control` (outlines of inputs and outlined buttons)
- **Action:** `bg-action`, `hover:bg-action-hover`, `text-on-action`,
  `bg-action-subtle`, `text-on-action-subtle`, `outline-focus`
- **Evidence:** `bg-evidence-highlight`, `border-evidence-stroke`,
  `bg-evidence-marker`, `text-on-evidence-marker`, and the `-active` pair for a
  marker whose source is open
- **Status:** `bg-{status}-bg`, `text-{status}-fg`, `border-{status}-border` for
  `candidate`, `validated`, `approved`, `rejected`, `superseded`, `success`,
  `info`, `caution` and `danger`
- **Palette:** `graphite-*`, `cobalt-*` and `ingot-*` steps, for the rare case
  no theme color fits
- **Type:** `text-display`, `text-title-1`, `text-title-2`, `text-title-3`,
  `text-body-lg`, `text-body`, `text-small`, `text-label`, `text-overline`,
  `text-quote`, `text-code`. Each sets size, line height and weight.
- **Fonts:** `font-sans` (the system), `font-serif` (words quoted from a
  source), `font-mono` (identifiers, URIs, scores, page numbers)
- **Radii:** `rounded-stamp` (badges, citation markers), `rounded-control`,
  `rounded-panel`, `rounded-pill` (facet chips only)
- **Shadows:** `shadow-popover`, `shadow-dialog`
- **Spacing:** the 4px grid. Use steps 0.5, 1, 2, 3, 4, 6, 8, 12 and 16
  (`p-4` is 16px). Control heights are `h-8` (compact), `h-10` (default) and
  `h-11` (touch).

## Rules

1. **Ingot means evidence.** Amber appears only on citation markers,
   highlighted spans and bounding boxes. Never use it for warnings or decoration.
2. **Status is never color alone.** Every lifecycle or feedback state renders
   with an icon and a text label. `approved` is the only filled status;
   `candidate` has a dashed border; `superseded` strikes its label.
3. **Three voices.** Interface text is sans. Text quoted from a document is
   `font-serif text-quote`. Identifiers and numbers are `font-mono` with
   `tabular-nums`. Overlines are `font-mono text-overline uppercase`.
4. **One primary action per region.** Rejecting is an outlined `danger`
   button, not a filled one, because a rejection is recorded, not erased.
5. **Abstentions are results.** Style them like answers, on `bg-surface` with a
   `border-border-control` outline. Do not use `danger` for them.
6. **Borders first.** Panels sit on the canvas with a hairline. Shadows are only
   for popovers, menus and dialogs.

## Changing a token

1. Edit `tokens.json`. Theme and status colors keep their dark value in
   `$extensions["org.ragfoundry"].dark`.
2. Run `python design-system/build_tokens.py`. It refuses to write the CSS if
   a text pair falls below 4.5:1, or a control outline, focus ring or evidence
   box falls below 3:1, in either theme.
3. Run `pytest tests/test_design_tokens.py`. It fails if the committed CSS is
   out of date.
