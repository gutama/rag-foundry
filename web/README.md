# RAG Foundry web

The React and TypeScript frontend, built on the Assay design system in
`../design-system/`. It holds Assay's components and patterns, and the Ask
screen that puts them together. Until the client API exists (ADR-0007), the
screens render the sample content in `src/fixtures/sample-data.ts`.

## Commands

```bash
npm ci
npm run dev        # dev server on http://localhost:5173
npm test           # Vitest, once
npm run coverage   # Vitest with a v8 coverage report
npm run lint       # gts (Google TypeScript style)
npm run build      # typecheck, then a production build in dist/
```

## Routes

| Hash | Shows |
|---|---|
| `#/ask` (default) | Ask: the answer with inline citations and the cited page beside it |
| `#/design` | Assay overview: principles and the three type voices |
| `#/design/components` | Buttons, inputs, facets, tabs, badges, citation markers, signals, messages, table |
| `#/design/evidence` | Grounded, partly supported and abstained answers, and the evidence panel |
| `#/design/governance` | Lifecycle, change-set review, concept card, audit trail, entity resolution |

The design-system pages have a System, Light or Dark switch. The choice is
stored in this browser and applies to the Ask screen too.

## Layout

| Folder | What it holds |
|---|---|
| `src/components/` | Controls and small building blocks: `Button`, `StatusBadge`, `CitationMarker`, `FacetChip`, `TextField`, `AskBar`, `SignalTag`, `DocumentTable` |
| `src/patterns/` | Composed patterns: `AnswerCard`, `AbstentionCard`, `EvidencePanel`, and the governance patterns |
| `src/screens/` | The Ask screen and the design-system pages |
| `src/lib/` | Claim counting, citation formatting, theme and class helpers |
| `src/types.ts` | Client types, owned by RAG Foundry rather than any RAG framework |

## Conventions

- Style only with the Assay utilities (`bg-surface`, `text-fg-muted`,
  `rounded-stamp`, and so on). Tailwind's default palette, type sizes, radii
  and shadows are switched off. See `../design-system/README.md`.
- Pages render on paper: wrap a document page in `data-theme="light"` so it
  stays light inside a dark app.
- Keep `build.cssTarget` in `vite.config.ts` at the browsers that support
  `light-dark()`, or nested themes break in production builds.
- Code follows `conductor/code_styleguides/typescript.md`: named exports,
  single quotes, and `gts` formatting.
