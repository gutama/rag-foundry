import {useState} from 'react';

import {Button} from '../../components/button';
import {InlineMessage} from '../../components/inline-message';
import {
  ABSTENTION,
  GROUNDED_ANSWER,
  PARTIAL_ANSWER,
  SOURCES,
} from '../../fixtures/sample-data';
import {AbstentionCard} from '../../patterns/abstention-card';
import {AnswerCard} from '../../patterns/answer-card';
import {EvidencePanel} from '../../patterns/evidence-panel';
import {Board, BoardHeader, Overline} from './board';

const RULES = [
  {
    title: 'Mark the clause, not the paragraph',
    text: 'A marker sits right after the clause it supports, before the full stop. One marker per source per claim.',
  },
  {
    title: 'One click to the exact span',
    text: 'Selecting a marker opens its source, scrolls the viewer to the bounding box, and inverts the marker while open.',
  },
  {
    title: 'Never cite what cannot be opened',
    text: 'Evidence the reader may not access is never shown or hinted at. Superseded evidence is excluded, and that is stated.',
  },
  {
    title: 'Abstain with a next step',
    text: 'Say what was searched and why it fell short, then offer a way forward. Never apologize, never guess.',
  },
];

/** Grounded, partly supported and abstained answers, and the evidence panel. */
export function EvidenceBoard() {
  const [openSource, setOpenSource] = useState<number | undefined>(1);

  return (
    <Board>
      <BoardHeader overline="04 · Patterns" title="Evidence">
        Answers come in three shapes: grounded, partly supported, and abstained.
        Each one shows its evidence the same way, so trust is earned from what
        is on screen, not from tone.
      </BoardHeader>

      <div className="grid grid-cols-1 items-start gap-12 lg:grid-cols-[7fr_5fr]">
        <div className="flex flex-col gap-8">
          <section className="flex flex-col gap-3">
            <Overline>A · Grounded answer</Overline>
            <div className="flex flex-col gap-1.5 px-1">
              <span className="text-label text-fg-muted">You asked</span>
              <h2 className="text-title-2">{GROUNDED_ANSWER.question}</h2>
            </div>
            <AnswerCard
              answer={GROUNDED_ANSWER}
              showProfile
              openSource={openSource}
              onSelectSource={setOpenSource}
              actions={
                <>
                  <Button variant="text" size="compact">
                    Copy with citations
                  </Button>
                  <Button variant="text" size="compact">
                    View trace
                  </Button>
                  <Button variant="text" size="compact">
                    Flag an issue
                  </Button>
                </>
              }
            />
          </section>

          <section className="flex flex-col gap-3">
            <Overline>B · Partly supported</Overline>
            <AnswerCard
              answer={PARTIAL_ANSWER}
              notice={
                <InlineMessage
                  tone="caution"
                  title="No source you can access says whether scans may replace originals"
                >
                  Treat the marked sentence as unverified. Ask a records
                  steward, or widen the scope.
                </InlineMessage>
              }
            />
          </section>

          <section className="flex flex-col gap-3">
            <Overline>C · Abstention</Overline>
            <AbstentionCard
              abstention={ABSTENTION}
              headingLevel={3}
              actions={
                <>
                  <Button>Widen scope</Button>
                  <Button variant="text">Ask a steward</Button>
                </>
              }
            />
          </section>
        </div>

        <aside className="flex flex-col gap-3">
          <Overline>D · Evidence panel</Overline>
          <EvidencePanel
            sources={SOURCES}
            openSource={openSource}
            onToggle={setOpenSource}
            excludedNote="1 passage from rev. 3 was excluded. Citations never point at superseded revisions."
          />
        </aside>
      </div>

      <section className="grid grid-cols-1 gap-6 border-t border-fg pt-5 sm:grid-cols-2 lg:grid-cols-4">
        {RULES.map((rule, i) => (
          <div key={rule.title} className="flex flex-col gap-1.5">
            <span className="font-mono text-label font-normal text-fg-muted">
              Rule {i + 1}
            </span>
            <h3 className="text-[0.9375rem] leading-5.5 font-semibold">
              {rule.title}
            </h3>
            <p className="text-small text-fg-secondary">{rule.text}</p>
          </div>
        ))}
      </section>
    </Board>
  );
}
