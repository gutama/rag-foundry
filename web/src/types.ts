/**
 * Client-side domain types. Per ADR-0007 these are RAG Foundry's own
 * contracts, never a framework's native objects.
 */

/** Review state of a governed object: a document, concept or assertion. */
export type LifecycleStatus =
  'candidate' | 'validated' | 'approved' | 'rejected' | 'superseded';

/** How far an answer is supported by the evidence the reader may open. */
export type AnswerSupport = 'grounded' | 'partial' | 'abstained';

/** Normalized page-coordinate box, matching the API's BoundingBox. */
export interface BoundingBox {
  page: number;
  l: number;
  t: number;
  r: number;
  b: number;
}

/** Where a passage ranked in each retrieval channel, and its fused scores. */
export interface RetrievalSignals {
  lexicalRank?: number;
  denseRank?: number;
  /** True when the optional graph provider returned the passage. */
  graph?: boolean;
  rrf?: number;
  rerank: number;
}

/** An excerpt split around the span that supports a claim. */
export interface Excerpt {
  before: string;
  cited: string;
  after: string;
}

/** A paragraph on a rendered document page. */
export interface PageBlock {
  kind: 'heading' | 'paragraph';
  text: string;
  /** Marks the block that holds the cited span. */
  cited?: boolean;
}

/** One cited source, numbered as its citation markers are. */
export interface Source {
  index: number;
  documentId: string;
  documentTitle: string;
  revision: string;
  status: LifecycleStatus;
  page: number;
  pageCount: number;
  /** Section, clause or table that holds the passage, e.g. "§3.2". */
  locator: string;
  chunkId: string;
  excerpt: Excerpt;
  signals: RetrievalSignals;
  bbox: BoundingBox;
  /** Page size in PDF points, used to label the bounding box. */
  pageSize: {width: number; height: number};
  /** Text layer of the cited page, for the document viewer. */
  pageBlocks: PageBlock[];
}

/** A run of answer text and the sources that support it. */
export interface AnswerSegment {
  text: string;
  /** Source indices cited right after this text, before any full stop. */
  citations?: number[];
  /** True when no evidence the reader may open supports this text. */
  unsupported?: boolean;
}

/** One sentence of an answer. Its clauses carry their own citations. */
export interface Claim {
  segments: AnswerSegment[];
}

/** A generated answer, split into claims. */
export interface Answer {
  question: string;
  support: AnswerSupport;
  claims: Claim[];
  /** Semantic profile used to expand the query, e.g. "records·v12". */
  profile: string;
  /** Taxonomy the answer's terms were checked against. */
  taxonomy: string;
}

/** What was searched before the system abstained. */
export interface Abstention {
  question: string;
  title: string;
  explanation: string;
  searched: string[];
  passagesScored: number;
  highestScore: number;
  threshold: number;
}

/** A row in a document list. */
export interface DocumentRow {
  id: string;
  title: string;
  collection: string;
  revision: string;
  pages: number;
  status: LifecycleStatus;
  updated: string;
}

/** Outcome of an automated check or a match signal. */
export type CheckResult = 'pass' | 'warn' | 'fail';

/** One automated check run against a change set. */
export interface Check {
  result: CheckResult;
  text: string;
  link?: {label: string; href: string};
}

/** One changed property in a change set. */
export interface DiffRow {
  op: 'add' | 'change' | 'remove';
  property: string;
  value: string;
  /** The value being replaced, for a change. */
  previous?: string;
}

/** A reviewed change to a schema, taxonomy, ontology or assertion set. */
export interface ChangeSet {
  id: string;
  kind: string;
  status: LifecycleStatus;
  title: string;
  proposer: string;
  baseVersion: string;
  publishesAs: string;
  diff: DiffRow[];
  checks: Check[];
}

/** A link to another governed object. */
export interface Ref {
  label: string;
  href: string;
}

/** A SKOS concept as stewards see it. */
export interface Concept {
  uri: string;
  status: LifecycleStatus;
  prefLabels: Array<{lang: string; label: string}>;
  altLabels: string[];
  broader: Ref[];
  narrower: Ref[];
  /** Semantic profile whose query expansion uses this concept. */
  profile: string;
  href: string;
}

/** One recorded transition in a governed object's history. */
export interface AuditEvent {
  status: LifecycleStatus;
  action: string;
  actor: string;
  at: string;
  reference: string;
}

/** An entity as it appears on either side of a resolution decision. */
export interface EntityRecord {
  id: string;
  name: string;
  type: string;
  origin: string;
  citedIn: number;
  status: LifecycleStatus;
}

/** A piece of evidence for or against merging two entities. */
export interface MatchSignal {
  result: CheckResult;
  label: string;
  value: string;
}
