import {Button} from '../../components/button';
import {
  AUDIT_EVENTS,
  CHANGE_SET,
  CONCEPT,
  ENTITY_MATCH,
} from '../../fixtures/sample-data';
import {
  AuditTrail,
  ChangeSetReview,
  ConceptCard,
  EntityResolution,
  LifecycleDiagram,
} from '../../patterns/governance';
import {Board, BoardHeader, Overline, SectionHeading} from './board';

/** Lifecycle, change-set review, concepts, audit trail, entity resolution. */
export function GovernanceBoard() {
  return (
    <Board>
      <BoardHeader overline="05 · Patterns" title="Governance">
        Schemas, taxonomies, ontologies and assertions change through reviewed
        change sets. The interface shows who proposed what, what the checks
        found, and what will be published, before anyone presses Approve.
      </BoardHeader>

      <section className="flex flex-col gap-5">
        <SectionHeading
          title="Assertion lifecycle"
          note="every transition is audited · nothing is deleted"
        />
        <LifecycleDiagram />
      </section>

      <div className="grid grid-cols-1 items-start gap-12 lg:grid-cols-[7fr_5fr]">
        <section className="flex flex-col gap-3">
          <Overline>A · Change set review</Overline>
          <ChangeSetReview changeSet={CHANGE_SET} />
        </section>
        <div className="flex flex-col gap-8">
          <section className="flex flex-col gap-3">
            <Overline>B · Concept card</Overline>
            <ConceptCard concept={CONCEPT} />
          </section>
          <section className="flex flex-col gap-3">
            <Overline>C · Audit trail</Overline>
            <AuditTrail events={AUDIT_EVENTS} />
          </section>
        </div>
      </div>

      <section className="flex flex-col gap-3">
        <Overline>D · Entity resolution</Overline>
        <EntityResolution
          {...ENTITY_MATCH}
          actions={
            <>
              <Button variant="text">Not sure</Button>
              <Button>Keep separate</Button>
              <Button variant="primary">
                Merge into {ENTITY_MATCH.existing.id.replace('ent:', '')}
              </Button>
            </>
          }
        />
      </section>
    </Board>
  );
}
