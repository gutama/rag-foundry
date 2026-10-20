import {CitationMarker} from '../../components/citation';
import {cx} from '../../lib/cx';
import {Overline} from './board';

const PRINCIPLES = [
  {
    title: 'Evidence before eloquence',
    text: 'A claim without a visible source is unfinished. Citations sit inline with the sentence they support, and one click opens the exact page and span.',
  },
  {
    title: 'Governance is visible',
    text: 'Candidate, validated, approved, rejected, superseded. Every governed object wears its lifecycle state as an icon and a label, never as color alone.',
  },
  {
    title: 'Abstain out loud',
    text: 'When the evidence is not enough, say so plainly and show what was searched. An abstention is a result, styled with the same care as an answer, not as an error.',
  },
  {
    title: 'Dense, never cramped',
    text: 'Analysts live in tables, facets and graphs. A 4 px grid, 14 px body text and hairline borders keep a lot on screen without visual noise.',
  },
];

/** The design system's cover: its name, its premise and its principles. */
export function OverviewBoard() {
  return (
    <>
      <div className="mx-auto grid w-full max-w-[90rem] grow grid-cols-1 content-start gap-12 px-4 pt-10 pb-10 sm:px-16 sm:pt-16 lg:grid-cols-[7fr_5fr] lg:gap-20">
        <section className="flex flex-col gap-7">
          <span className="font-mono text-label tracking-[0.08em] text-fg-muted uppercase">
            Design system
          </span>
          <h1 className="text-[5rem] leading-[0.95] font-semibold tracking-[-0.035em] sm:text-[8rem]">
            Assay
          </h1>
          <p className="max-w-[42.5rem] text-[1.5rem] leading-8 font-medium tracking-[-0.01em] sm:text-[1.875rem] sm:leading-[2.375rem]">
            A visual language for governed, evidence-first document
            intelligence.
          </p>
          <p className="max-w-[40rem] font-serif text-[1.1875rem] leading-[1.875rem] text-fg-secondary">
            An assay office tests metal and stamps it with a hallmark of origin
            and purity. RAG Foundry holds answers to the same standard: every
            claim carries a mark that traces it to its source
            <CitationMarker index={1} inline />
            , and every governed object shows the state it has earned
            <CitationMarker index={2} inline />.
          </p>
        </section>
        <ol className="flex flex-col">
          {PRINCIPLES.map((principle, i) => (
            <li
              key={principle.title}
              className={cx(
                'flex gap-5 border-t py-5.5',
                i === 0 ? 'border-fg' : 'border-border',
                i === PRINCIPLES.length - 1 && 'border-b',
              )}
            >
              <span className="w-7 shrink-0 font-mono text-small leading-6.5 text-fg-muted">
                {String(i + 1).padStart(2, '0')}
              </span>
              <div className="flex flex-col gap-1.5">
                <h2 className="text-[1.1875rem] leading-6.5 font-semibold">
                  {principle.title}
                </h2>
                <p className="text-body text-fg-secondary">{principle.text}</p>
              </div>
            </li>
          ))}
        </ol>
      </div>
      <footer className="border-t border-border bg-surface">
        <div className="mx-auto grid w-full max-w-[90rem] grid-cols-1 gap-8 px-4 pt-7 pb-8 sm:px-16 md:grid-cols-3 md:gap-12">
          <div className="flex flex-col gap-2">
            <Overline>The system speaks · IBM Plex Sans</Overline>
            <span className="text-[1.375rem] leading-7.5 font-medium">
              Search 3 collections you can access
            </span>
          </div>
          <div className="flex flex-col gap-2">
            <Overline>The source speaks · Source Serif 4</Overline>
            <span className="font-serif text-[1.375rem] leading-7.5">
              “Records are retained as set out in Schedule B.”
            </span>
          </div>
          <div className="flex flex-col gap-2">
            <Overline>The machine speaks · IBM Plex Mono</Overline>
            <span className="font-mono text-[1.25rem] leading-7.5">
              chunk:0f3a91 · p.12 · rrf 0.032
            </span>
          </div>
        </div>
      </footer>
    </>
  );
}
