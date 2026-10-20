/**
 * Sample content for the Ask screen and the design-system gallery, taken
 * from the Assay design. It stands in for API responses until the client
 * contract exists.
 */

import type {
  Abstention,
  Answer,
  AuditEvent,
  ChangeSet,
  Concept,
  DocumentRow,
  EntityRecord,
  MatchSignal,
  Source,
} from '../types';

/** US Letter in PDF points. */
const LETTER = {width: 612, height: 792};

export const SOURCES: Source[] = [
  {
    index: 1,
    documentId: 'doc:rrp',
    documentTitle: 'Records Retention Policy',
    revision: 'rev. 4',
    status: 'approved',
    page: 12,
    pageCount: 18,
    locator: '§3.2',
    chunkId: 'chunk:0f3a91',
    excerpt: {
      before: '3.2 ',
      cited:
        'Vendor contract records are retained for the period set out in Schedule B. The period begins on the date the contract expires.',
      after: '',
    },
    signals: {lexicalRank: 2, denseRank: 1, rrf: 0.032, rerank: 0.91},
    bbox: {page: 12, l: 72 / 612, t: 318 / 792, r: 540 / 612, b: 372 / 792},
    pageSize: LETTER,
    pageBlocks: [
      {kind: 'heading', text: '3. Retention periods'},
      {
        kind: 'paragraph',
        text: '3.1 Each record class has one retention period, listed in Schedule B. Where two classes apply to the same record, the longer period is used.',
      },
      {
        kind: 'paragraph',
        text: '3.2 Vendor contract records are retained for the period set out in Schedule B. The period begins on the date the contract expires.',
        cited: true,
      },
      {
        kind: 'paragraph',
        text: '3.3 Records under a legal hold are kept until the hold is released, whatever Schedule B provides.',
      },
      {
        kind: 'paragraph',
        text: '3.4 Copies made for convenience are not records and follow the period of the original.',
      },
      {kind: 'heading', text: '4. Disposal'},
      {
        kind: 'paragraph',
        text: '4.1 The records office confirms disposal with the record owner before any record is destroyed, and keeps a disposal certificate.',
      },
      {
        kind: 'paragraph',
        text: '4.2 Disposal of records in electronic systems includes backups held beyond the standard rotation.',
      },
    ],
  },
  {
    index: 2,
    documentId: 'doc:rsb',
    documentTitle: 'Records Schedule B',
    revision: 'rev. 2',
    status: 'approved',
    page: 2,
    pageCount: 6,
    locator: 'table 1',
    chunkId: 'chunk:7c20d4',
    excerpt: {
      before: 'Table 1. ',
      cited:
        'Supplier agreements form their own record class, separate from finance and personnel records.',
      after: '',
    },
    signals: {lexicalRank: 1, denseRank: 4, rrf: 0.03, rerank: 0.84},
    bbox: {page: 2, l: 72 / 612, t: 140 / 792, r: 540 / 612, b: 188 / 792},
    pageSize: LETTER,
    pageBlocks: [
      {kind: 'heading', text: 'Table 1. Record classes'},
      {
        kind: 'paragraph',
        text: 'Supplier agreements form their own record class, separate from finance and personnel records.',
        cited: true,
      },
    ],
  },
  {
    index: 3,
    documentId: 'doc:vms',
    documentTitle: 'Vendor Management Standard',
    revision: 'rev. 11',
    status: 'approved',
    page: 31,
    pageCount: 42,
    locator: '§8.4',
    chunkId: 'chunk:b51e07',
    excerpt: {
      before: '8.4 ',
      cited:
        'The contract owner confirms disposal of contract records with the records office.',
      after: '',
    },
    signals: {denseRank: 2, graph: true, rrf: 0.016, rerank: 0.62},
    bbox: {page: 31, l: 72 / 612, t: 402 / 792, r: 540 / 612, b: 438 / 792},
    pageSize: LETTER,
    pageBlocks: [
      {kind: 'heading', text: '8. Contract closure'},
      {
        kind: 'paragraph',
        text: '8.4 The contract owner confirms disposal of contract records with the records office.',
        cited: true,
      },
    ],
  },
];

export const GROUNDED_ANSWER: Answer = {
  question: 'How long do we keep vendor contract records?',
  support: 'grounded',
  profile: 'records·v12',
  taxonomy: 'records-taxonomy v12',
  claims: [
    {
      segments: [
        {
          text: 'Vendor contract records are kept for the period set out in Schedule B of the Records Retention Policy',
          citations: [1],
        },
        {text: '.'},
      ],
    },
    {
      segments: [
        {
          text: 'The period starts on the date the contract expires, not the date it was signed',
          citations: [1],
        },
        {text: '.'},
      ],
    },
    {
      segments: [
        {
          text: 'Schedule B lists supplier agreements as their own record class, separate from finance and personnel records',
          citations: [2],
        },
        {
          text: ', and the Vendor Management Standard requires the contract owner to confirm disposal',
          citations: [3],
        },
        {text: '.'},
      ],
    },
  ],
};

export const PARTIAL_ANSWER: Answer = {
  question: 'Can scanned copies replace signed vendor contracts?',
  support: 'partial',
  profile: 'records·v12',
  taxonomy: 'records-taxonomy v12',
  claims: [
    {
      segments: [
        {
          text: 'Signed originals of vendor contracts go to the records office within 30 days of signature',
          citations: [1],
        },
        {text: '.'},
      ],
    },
    {
      segments: [
        {
          text: 'Scanned copies may replace the originals after that.',
          unsupported: true,
        },
      ],
    },
  ],
};

export const ABSTENTION: Abstention = {
  question: 'May staff keep personal messages on work devices?',
  title: 'Not enough evidence to answer',
  explanation:
    'None of the passages in the collections you can access address keeping personal messages on work devices. Nothing was generated.',
  searched: ['Policies', 'Standards', 'Minutes'],
  passagesScored: 214,
  highestScore: 0.31,
  threshold: 0.55,
};

export const DOCUMENTS: DocumentRow[] = [
  {
    id: 'doc:rrp',
    title: 'Records Retention Policy',
    collection: 'Policies',
    revision: 'rev. 4',
    pages: 18,
    status: 'approved',
    updated: '7 Aug 2026',
  },
  {
    id: 'doc:vms',
    title: 'Vendor Management Standard',
    collection: 'Standards',
    revision: 'rev. 11',
    pages: 42,
    status: 'validated',
    updated: '30 Sep 2026',
  },
  {
    id: 'doc:bmq2',
    title: 'Board minutes, Q2',
    collection: 'Minutes',
    revision: 'rev. 1',
    pages: 9,
    status: 'candidate',
    updated: '1 Oct 2026',
  },
  {
    id: 'doc:rrp',
    title: 'Records Retention Policy',
    collection: 'Policies',
    revision: 'rev. 3',
    pages: 17,
    status: 'superseded',
    updated: '12 Jan 2025',
  },
];

export const CHANGE_SET: ChangeSet = {
  id: 'CS-0142',
  kind: 'taxonomy',
  status: 'validated',
  title: 'Add Indonesian labels to Records retention concepts',
  proposer: '[Proposer name]',
  baseVersion: 'records-taxonomy v12',
  publishesAs: 'records-taxonomy v13',
  diff: [
    {op: 'add', property: 'altLabel @id', value: '“masa retensi”'},
    {op: 'add', property: 'prefLabel @id', value: '“arsip kontrak vendor”'},
    {
      op: 'change',
      property: 'broader',
      previous: 'rf:records',
      value: 'rf:contract-records',
    },
    {op: 'remove', property: 'altLabel @en', value: '“supplier file”'},
  ],
  checks: [
    {
      result: 'pass',
      text: 'SKOS integrity: no cycles, one prefLabel per language',
    },
    {
      result: 'pass',
      text: 'Backward compatible: no concept removed or renamed',
    },
    {
      result: 'warn',
      text: 'Query expansion changes for 2 saved searches',
      link: {label: 'Preview', href: '#'},
    },
  ],
};

export const CONCEPT: Concept = {
  uri: 'rf:vendor-contract-records',
  status: 'approved',
  prefLabels: [
    {lang: 'en', label: 'Vendor contract records'},
    {lang: 'id', label: 'Arsip kontrak vendor'},
  ],
  altLabels: ['supplier agreements', 'masa retensi'],
  broader: [{label: 'Contract records', href: '#'}],
  narrower: [
    {label: 'Framework agreements', href: '#'},
    {label: 'Purchase orders', href: '#'},
  ],
  profile: 'records·v12',
  href: '#',
};

export const AUDIT_EVENTS: AuditEvent[] = [
  {
    status: 'validated',
    action: 'Validated',
    actor: 'validation job',
    at: '2026-10-01 14:22 UTC',
    reference: 'job:val-88f2',
  },
  {
    status: 'candidate',
    action: 'Proposed',
    actor: '[Proposer name]',
    at: '2026-10-01 14:19 UTC',
    reference: 'base v12',
  },
  {
    status: 'approved',
    action: 'v12 published',
    actor: '[Reviewer name]',
    at: '2026-08-07 09:05 UTC',
    reference: 'CS-0131',
  },
];

export const ENTITY_MATCH: {
  existing: EntityRecord;
  candidate: EntityRecord;
  signals: MatchSignal[];
} = {
  existing: {
    id: 'ent:org-2291',
    name: 'Meridian Cargo Ltd.',
    type: 'Organization',
    origin: 'from the vendor register',
    citedIn: 14,
    status: 'approved',
  },
  candidate: {
    id: 'ent:org-3107',
    name: 'Meridian Cargo Limited',
    type: 'Organization',
    origin: 'extracted from contracts',
    citedIn: 3,
    status: 'candidate',
  },
  signals: [
    {result: 'pass', label: 'Name similarity', value: '0.94'},
    {result: 'pass', label: 'Same registration number', value: 'match'},
    {result: 'warn', label: 'Different security domain', value: 'review'},
  ],
};
