import {useEffect, useState} from 'react';

import {Button} from '../../components/button';
import {ScopeChip} from '../../components/facets';
import {AskBar} from '../../components/fields';
import {formatAnswerWithCitations} from '../../lib/citations';
import {AnswerCard} from '../../patterns/answer-card';
import type {Answer, Source} from '../../types';
import {AppNav, NAV_ITEMS} from './app-nav';
import {DocumentViewer} from './document-viewer';

interface AskScreenProps {
  answer: Answer;
  sources: Source[];
  /** Collections the question was scoped to. */
  scope: string[];
  followUps: string[];
  deployment: string;
  /** Reviews waiting in Stewardship. */
  pendingReviews?: number;
  onAsk?: (question: string) => void;
  onViewTrace?: () => void;
}

/**
 * Ask: the answer with its citations, and the cited page open beside it.
 * Selecting a marker opens that source in the viewer.
 */
export function AskScreen({
  answer,
  sources,
  scope,
  followUps,
  deployment,
  pendingReviews,
  onAsk = () => {},
  onViewTrace,
}: AskScreenProps) {
  const [openSource, setOpenSource] = useState(sources[0]?.index);
  const [copied, setCopied] = useState(false);
  const source = sources.find(s => s.index === openSource) ?? sources[0];

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);

  function copyWithCitations() {
    const text = formatAnswerWithCitations(answer, sources);
    navigator.clipboard?.writeText(text).then(
      () => setCopied(true),
      () => setCopied(false),
    );
  }

  const nav = NAV_ITEMS.map(item =>
    item.id === 'stewardship' ? {...item, count: pendingReviews} : item,
  );

  return (
    <div className="flex min-h-screen flex-wrap items-stretch bg-bg text-fg">
      <AppNav items={nav} current="ask" deployment={deployment} />

      <main className="flex min-w-0 flex-[1000_1_30rem] flex-col">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-border px-8 py-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-small text-fg-muted">Scope</span>
            {scope.map(name => (
              <ScopeChip key={name} label={name} />
            ))}
          </div>
          <span className="font-mono text-label font-normal text-fg-muted">
            profile {answer.profile}
          </span>
        </div>

        <div className="flex w-full max-w-[47.5rem] grow flex-col gap-5 p-8">
          <div className="flex flex-col gap-1.5">
            <span className="text-label text-fg-muted">You asked</span>
            <h1 className="text-title-2">{answer.question}</h1>
          </div>
          <AnswerCard
            answer={answer}
            openSource={openSource}
            onSelectSource={setOpenSource}
            actions={
              <>
                <Button
                  variant="text"
                  size="compact"
                  onClick={copyWithCitations}
                >
                  {copied ? 'Copied' : 'Copy with citations'}
                </Button>
                <Button variant="text" size="compact" onClick={onViewTrace}>
                  View trace
                </Button>
              </>
            }
          />
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-small text-fg-muted">Follow up</span>
            {followUps.map(question => (
              <button
                key={question}
                type="button"
                onClick={() => onAsk(question)}
                className="h-8 rounded-control border border-border-control bg-transparent px-3 text-small text-fg hover:bg-surface"
              >
                {question}
              </button>
            ))}
          </div>
        </div>

        <div className="w-full max-w-[47.5rem] px-8 pt-4 pb-6">
          <AskBar placeholder="Ask a follow-up" onAsk={onAsk} />
        </div>
      </main>

      {source && <DocumentViewer source={source} />}
    </div>
  );
}
