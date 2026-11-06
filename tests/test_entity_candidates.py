"""Tests for mention normalization and resolution candidate generation."""

import uuid

import pytest

from rag_foundry.entities import resolution as res
from rag_foundry.entities.models import Entity, Mention
from tests.ontology_samples import EX, build_finance_release

WS = uuid.UUID("00000000-0000-4000-8000-0000000000aa")
OTHER_WS = uuid.UUID("00000000-0000-4000-8000-0000000000cc")
PROFILE = uuid.UUID("00000000-0000-4000-8000-0000000000bb")
ID = "http://id.example.org/entity/"


def _entity(name, labels, cls="Bank", **kwargs):
    """Build an entity in the test workspace."""
    fields = {
        "workspace_id": WS,
        "semantic_profile_id": PROFILE,
        "canonical_uri": ID + name,
        "ontology_class_uri": EX + cls,
        "preferred_labels": labels,
    }
    fields.update(kwargs)
    return Entity(**fields)


def _mention(text, **kwargs):
    """Build a mention in the test workspace."""
    fields = {
        "workspace_id": WS,
        "semantic_profile_id": PROFILE,
        "chunk_id": uuid.uuid4(),
        "start_offset": 0,
        "end_offset": len(text),
        "surface_text": text,
    }
    fields.update(kwargs)
    return Mention(**fields)


def _uris(candidates):
    """List candidate canonical IRIs without the namespace."""
    return [c.canonical_uri[len(ID):] for c in candidates]


@pytest.fixture
def banks():
    """A few entities with labels, aliases and identifiers."""
    return [
        _entity(
            "bca",
            {"en": "Bank Central Asia", "id": "PT Bank Central Asia Tbk"},
            aliases={"en": ["BCA"]},
            identifiers={"swift_bic": "CENAIDJA"},
        ),
        _entity(
            "bri",
            {"en": "Bank Rakyat Indonesia"},
            aliases={"en": ["BRI"]},
            identifiers={"swift_bic": "BRINIDJA", "lei": "LEI-BRI"},
        ),
        _entity("mandiri", {"en": "Bank Mandiri"}),
        _entity("ojk", {"en": "Otoritas Jasa Keuangan"}, cls="Regulator",
                aliases={"en": ["OJK", "Financial Services Authority"]}),
        _entity("budi", {"id": "Budi Santoso"}, cls="Person"),
    ]


# --- Normalization --------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("  PT. Bank   Central Asia, Tbk. ", "pt bank central asia tbk"),
        ("Bánk Céntral Ásia", "bank central asia"),
        ("ＢＣＡ", "bca"),
        ("Straße", "strasse"),
        ("Bank\tCentral\nAsia", "bank central asia"),
        ("O'Neil & Sons (Pte) Ltd.", "o neil sons pte ltd"),
        ("ﬁnance", "finance"),
        ("...", ""),
    ],
)
def test_normalize_text(text, expected):
    """Normalization folds case, accents, width, punctuation and spaces."""
    assert res.normalize_text(text) == expected


def test_normalizer_is_versioned():
    """Stored candidates can name the normalizer that produced them."""
    assert res.NORMALIZER_VERSION == "1"


# --- Signals and ranking --------------------------------------------------


def test_identifier_match_outranks_label_match(banks):
    """A shared identifier beats an exact label of another entity."""
    mention = _mention("Bank Central Asia", identifiers={"lei": "LEI-BRI"})
    candidates = res.CandidateGenerator().generate(mention, banks)
    assert _uris(candidates)[:2] == ["bri", "bca"]
    assert candidates[0].method == "identifier"
    assert candidates[0].score == 1.0
    assert candidates[0].matched_text == "lei:LEI-BRI"
    assert candidates[1].method == "exact_label"
    assert candidates[1].score == pytest.approx(0.95)


def test_identifier_match_needs_no_name_similarity(banks):
    """Identifiers resolve even when the text is a description."""
    mention = _mention(
        "the lender", identifiers={"swift_bic": "CENAIDJA"}
    )
    candidates = res.CandidateGenerator().generate(mention, banks)
    assert _uris(candidates) == ["bca"]


def test_exact_label_match_after_normalization(banks):
    """Labels match regardless of case, accents and punctuation."""
    candidates = res.CandidateGenerator().generate(
        _mention("PT. BANK CÉNTRAL ASIA, TBK."), banks
    )
    assert _uris(candidates)[0] == "bca"
    assert candidates[0].method == "exact_label"
    assert candidates[0].matched_text == "PT Bank Central Asia Tbk"


def test_alias_match(banks):
    """Aliases match exactly, scoring just below labels."""
    candidates = res.CandidateGenerator().generate(_mention("ojk"), banks)
    assert _uris(candidates) == ["ojk"]
    assert candidates[0].method == "exact_alias"
    assert candidates[0].score == pytest.approx(0.9)


def test_label_match_outranks_alias_match():
    """An exact label beats an exact alias of another entity."""
    entities = [
        _entity("a", {"en": "Alpha"}, aliases={"en": ["Delta"]}),
        _entity("d", {"en": "Delta"}),
    ]
    candidates = res.CandidateGenerator().generate(_mention("delta"), entities)
    assert _uris(candidates) == ["d", "a"]


def test_similarity_ranking(banks):
    """Near matches rank by similarity, below every exact match."""
    candidates = res.CandidateGenerator(min_similarity=0.6).generate(
        _mention("Bank Centrl Asia"), banks
    )
    assert _uris(candidates)[0] == "bca"
    top = candidates[0]
    assert top.method == "similarity"
    assert top.score < 0.9
    assert top.score == pytest.approx(
        0.85 * top.score_breakdown["similarity"]
    )
    scores = [c.score for c in candidates]
    assert scores == sorted(scores, reverse=True)


def test_similarity_ignores_token_order(banks):
    """Reordered names still match through sorted tokens."""
    candidates = res.CandidateGenerator().generate(
        _mention("Central Asia Bank"), banks
    )
    assert _uris(candidates)[0] == "bca"
    assert candidates[0].score_breakdown["similarity"] == pytest.approx(1.0)


def test_similarity_threshold(banks):
    """Matches below min_similarity are not candidates."""
    mention = _mention("Bank Centrl Asia")
    strict = res.CandidateGenerator(min_similarity=0.99).generate(
        mention, banks
    )
    assert strict == []


def test_score_breakdown_records_every_signal(banks):
    """Each candidate explains every signal, not only the winning one."""
    mention = _mention("BCA", identifiers={"swift_bic": "CENAIDJA"})
    (candidate,) = res.CandidateGenerator().generate(mention, banks)
    assert candidate.score_breakdown == {
        "identifier": 1.0,
        "exact_label": 0.0,
        "exact_alias": 1.0,
        "similarity": pytest.approx(1.0),
    }
    assert candidate.method == "identifier"
    assert candidate.entity_id == banks[0].id


def test_no_candidates(banks):
    """Unknown names produce no candidates."""
    assert res.CandidateGenerator().generate(_mention("Zeta"), banks) == []


def test_punctuation_only_mention_matches_nothing(banks):
    """Text that normalizes to nothing never matches by name."""
    generator = res.CandidateGenerator(min_similarity=0.0)
    assert generator.generate(_mention("..."), banks) == []


# --- Filters --------------------------------------------------------------


def test_identifier_conflict_excludes_entity(banks):
    """A different value in the same scheme proves a different entity."""
    mention = _mention(
        "Bank Central Asia", identifiers={"swift_bic": "XXXXIDJA"}
    )
    candidates = res.CandidateGenerator().generate(mention, banks)
    assert "bca" not in _uris(candidates)


def test_class_filter_uses_subclasses():
    """With a release, entity classes must be the hint or a subclass."""
    release = build_finance_release()
    entities = [
        _entity("acme-bank", {"en": "Acme"}, cls="Bank"),
        _entity("acme-org", {"en": "Acme"}, cls="Organization"),
        _entity("acme-person", {"en": "Acme"}, cls="Person"),
        _entity("acme-robot", {"en": "Acme"}, cls="Robot"),
    ]
    generator = res.CandidateGenerator(release=release)
    as_org = generator.generate(
        _mention("Acme", ontology_class_uri=EX + "Organization"), entities
    )
    as_bank = generator.generate(
        _mention("Acme", ontology_class_uri=EX + "Bank"), entities
    )
    untyped = generator.generate(_mention("Acme"), entities)
    assert sorted(_uris(as_org)) == ["acme-bank", "acme-org"]
    assert _uris(as_bank) == ["acme-bank"]
    assert len(untyped) == 4


def test_class_filter_without_release_requires_same_class():
    """Without a release, only the exact class is compatible."""
    entities = [
        _entity("acme-bank", {"en": "Acme"}, cls="Bank"),
        _entity("acme-org", {"en": "Acme"}, cls="Organization"),
    ]
    candidates = res.CandidateGenerator().generate(
        _mention("Acme", ontology_class_uri=EX + "Organization"), entities
    )
    assert _uris(candidates) == ["acme-org"]


def test_only_active_entities_in_the_workspace(banks):
    """Inactive entities and other workspaces are never candidates."""
    entities = [
        _entity("old", {"en": "Bank Central Asia"}, status="deprecated"),
        _entity("gone", {"en": "Bank Central Asia"}, status="merged",
                merged_into_id=uuid.uuid4()),
        _entity("elsewhere", {"en": "Bank Central Asia"},
                workspace_id=OTHER_WS),
        banks[0],
    ]
    candidates = res.CandidateGenerator().generate(
        _mention("Bank Central Asia"), entities
    )
    assert _uris(candidates) == ["bca"]


def test_max_candidates_and_tie_order():
    """Ties break on canonical IRI; the list is truncated."""
    entities = [
        _entity(name, {"en": "Acme"}) for name in ("c", "a", "d", "b")
    ]
    candidates = res.CandidateGenerator(max_candidates=3).generate(
        _mention("Acme"), entities
    )
    assert _uris(candidates) == ["a", "b", "c"]


def test_generation_is_deterministic(banks):
    """Identical inputs give identical candidates."""
    generator = res.CandidateGenerator(min_similarity=0.5)
    mention = _mention("Bank Indonesia")
    first = generator.generate(mention, banks)
    second = generator.generate(mention, list(reversed(banks)))
    assert [c.model_dump() for c in first] == [
        c.model_dump() for c in second
    ]


@pytest.mark.parametrize(
    "kwargs", [{"min_similarity": 1.5}, {"max_candidates": 0}]
)
def test_generator_settings_are_validated(kwargs):
    """Thresholds and limits must be sensible."""
    with pytest.raises(ValueError):
        res.CandidateGenerator(**kwargs)
