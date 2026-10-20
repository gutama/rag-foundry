import {useState} from 'react';

import {AnswerBadge, StatusBadge} from '../../components/badge';
import {Button, IconButton} from '../../components/button';
import {CitationMarker, SourcePreview} from '../../components/citation';
import {DocumentTable} from '../../components/document-table';
import {FacetChip, SegmentedControl, Tabs} from '../../components/facets';
import {AskBar, SelectField, TextField} from '../../components/fields';
import {ArrowRightIcon, SearchIcon} from '../../components/icons';
import {InlineMessage} from '../../components/inline-message';
import {RetrievalSignalRow} from '../../components/signals';
import {DOCUMENTS, SOURCES} from '../../fixtures/sample-data';
import type {LifecycleStatus} from '../../types';
import {Board, BoardHeader, Overline, SectionHeading, Specimen} from './board';

const STATUSES: LifecycleStatus[] = [
  'candidate',
  'validated',
  'approved',
  'rejected',
  'superseded',
];

const FACETS = [
  {label: 'Policy', count: 128},
  {label: 'Contract', count: 64},
  {label: 'Minutes', count: 31},
  {label: 'Regulation', count: 12},
];

type Mode = 'hybrid' | 'lexical' | 'dense' | 'graph';

function ButtonsSection() {
  return (
    <section className="flex flex-col gap-4">
      <SectionHeading title="Buttons" note="radius-control · 14 / 500" />
      <Overline>Variants</Overline>
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" trailingIcon={<ArrowRightIcon />}>
          Ask
        </Button>
        <Button>Add filter</Button>
        <Button variant="text">Cancel</Button>
        <Button variant="danger">Reject change</Button>
        <IconButton label="Search">
          <SearchIcon size={18} />
        </IconButton>
      </div>
      <Overline className="mt-2">States</Overline>
      <div className="flex flex-wrap items-start gap-4">
        <Specimen caption="default">
          <Button variant="primary">Publish</Button>
        </Specimen>
        <Specimen caption="hover">
          <Button
            variant="primary"
            tabIndex={-1}
            style={{background: 'var(--rf-action-hover)'}}
          >
            Publish
          </Button>
        </Specimen>
        <Specimen caption="focus · 2 + 2 ring">
          <Button
            variant="primary"
            tabIndex={-1}
            className="outline-2 outline-offset-2 outline-focus"
          >
            Publish
          </Button>
        </Specimen>
        <Specimen caption="disabled">
          <Button variant="primary" disabled>
            Publish
          </Button>
        </Specimen>
        <Specimen caption="busy">
          <Button variant="primary" busy>
            Searching
          </Button>
        </Specimen>
      </div>
      <Overline className="mt-2">Sizes</Overline>
      <div className="flex flex-wrap items-end gap-4">
        <Specimen caption="compact · 32">
          <Button size="compact">Export</Button>
        </Specimen>
        <Specimen caption="default · 40">
          <Button>Export</Button>
        </Specimen>
        <Specimen caption="touch · 44">
          <Button size="touch">Export</Button>
        </Specimen>
      </div>
    </section>
  );
}

function InputsSection() {
  const [date, setDate] = useState('07/08/2026');
  const dateError = /^\d{4}-\d{2}-\d{2}$/.test(date)
    ? undefined
    : 'Use an ISO 8601 date: YYYY-MM-DD.';
  return (
    <section className="flex flex-col gap-4">
      <SectionHeading title="Inputs" note="label above · error below" />
      <AskBar scopeLabel="Scope · 3 collections" onAsk={() => {}} />
      <div className="mt-2 grid grid-cols-1 gap-5 sm:grid-cols-2">
        <TextField
          label="Effective date"
          value={date}
          onChange={event => setDate(event.target.value)}
          error={dateError}
          meta="policy-document v3 · effective_date"
        />
        <SelectField
          label="Semantic profile"
          options={['records · v12', 'records · v11']}
          hint="Taxonomy and ontology used to expand the query."
        />
      </div>
    </section>
  );
}

function FacetsSection() {
  const [selected, setSelected] = useState(new Set(['Policy']));
  const [tab, setTab] = useState('answer');
  const [mode, setMode] = useState<Mode>('hybrid');

  function toggle(label: string) {
    const next = new Set(selected);
    if (next.has(label)) {
      next.delete(label);
    } else {
      next.add(label);
    }
    setSelected(next);
  }

  return (
    <section className="flex flex-col gap-4">
      <SectionHeading title="Facets and navigation" note="counts in mono" />
      <div className="flex flex-wrap items-center gap-2">
        {FACETS.map(facet => (
          <FacetChip
            key={facet.label}
            label={facet.label}
            count={facet.count}
            selected={selected.has(facet.label)}
            onToggle={() => toggle(facet.label)}
          />
        ))}
        <button
          type="button"
          onClick={() => setSelected(new Set())}
          className="ml-1 text-small text-link underline"
        >
          Clear
        </button>
      </div>
      <div className="mt-2 flex flex-wrap items-end justify-between gap-6">
        <Tabs
          label="Result views"
          tabs={[
            {id: 'answer', label: 'Answer'},
            {id: 'sources', label: 'Sources', count: 3},
            {id: 'trace', label: 'Trace'},
          ]}
          selected={tab}
          onSelect={setTab}
        />
        <SegmentedControl<Mode>
          label="Retrieval mode"
          options={[
            {value: 'hybrid', label: 'Hybrid'},
            {value: 'lexical', label: 'Lexical'},
            {value: 'dense', label: 'Dense'},
            {value: 'graph', label: 'Graph'},
          ]}
          value={mode}
          onChange={setMode}
        />
      </div>
    </section>
  );
}

function BadgesSection() {
  return (
    <section className="flex flex-col gap-4">
      <SectionHeading title="Status badges" note="radius-stamp · 24 high" />
      <Overline>Governed objects</Overline>
      <div className="flex flex-wrap items-center gap-2">
        {STATUSES.map(status => (
          <StatusBadge key={status} status={status} />
        ))}
      </div>
      <Overline className="mt-1">Answer validation</Overline>
      <div className="flex flex-wrap items-center gap-2">
        <AnswerBadge support="grounded" cited={3} total={3} />
        <AnswerBadge support="partial" />
        <AnswerBadge support="abstained" />
      </div>
    </section>
  );
}

function CitationSection() {
  return (
    <section className="flex flex-col gap-4">
      <SectionHeading
        title="Citation marker"
        note="ingot-200 · mono 11 / 500"
      />
      <div className="flex flex-wrap items-start gap-5">
        <Specimen caption="default">
          <CitationMarker index={1} onSelect={() => {}} />
        </Specimen>
        <Specimen caption="hover · focus">
          <CitationMarker
            index={1}
            style={{
              background: 'var(--rf-ingot-300)',
              outline: '1.5px solid var(--rf-ingot-700)',
              outlineOffset: 2,
            }}
          />
        </Specimen>
        <Specimen caption="open in panel">
          <CitationMarker index={1} state="open" onSelect={() => {}} />
        </Specimen>
        <Specimen caption="failed validation">
          <CitationMarker index={4} state="failed" onSelect={() => {}} />
        </Specimen>
      </div>
      <SourcePreview source={SOURCES[0]} className="w-full max-w-[25rem]" />
    </section>
  );
}

function SignalsSection() {
  return (
    <section className="flex flex-col gap-3">
      <SectionHeading
        title="Retrieval signal"
        note="channel rank · rerank score"
      />
      {SOURCES.map((source, i) => (
        <RetrievalSignalRow
          key={source.index}
          rank={i + 1}
          title={source.documentTitle}
          signals={source.signals}
        />
      ))}
      <p className="text-label leading-[1.125rem] font-normal text-fg-muted">
        Graph is dashed: it is an optional provider and its hits are explained,
        never assumed.
      </p>
    </section>
  );
}

function MessagesSection() {
  return (
    <section className="flex flex-col gap-2.5">
      <SectionHeading title="Inline messages" note="title + one line" />
      <InlineMessage
        tone="info"
        title="Results are limited to sources you can access"
      >
        Ask a collection owner if you expected more.
      </InlineMessage>
      <InlineMessage tone="caution" title="Part of this answer is unsupported">
        One sentence had no authorized evidence and is marked in the text.
      </InlineMessage>
      <InlineMessage tone="danger" title="Publication blocked">
        2 SHACL violations in this change set. Fix them before requesting
        approval.
      </InlineMessage>
    </section>
  );
}

/** Controls, badges, citation markers, signals, messages and tables. */
export function ComponentsBoard() {
  return (
    <Board>
      <BoardHeader overline="03 · Components" title="Components">
        Plain, sturdy controls. Cobalt marks the one primary action in a region.
        Rejecting is outlined, not filled, because a rejection is recorded, not
        erased.
      </BoardHeader>
      <div className="grid grid-cols-1 gap-14 lg:grid-cols-2">
        <div className="flex flex-col gap-10">
          <ButtonsSection />
          <InputsSection />
          <FacetsSection />
        </div>
        <div className="flex flex-col gap-10">
          <BadgesSection />
          <CitationSection />
          <SignalsSection />
          <MessagesSection />
        </div>
      </div>
      <section className="flex flex-col gap-3">
        <SectionHeading
          title="Data table"
          note="compact rows · ids and numbers in mono · selected row in cobalt-50"
        />
        <DocumentTable rows={DOCUMENTS} selectedRow={1} />
      </section>
    </Board>
  );
}
