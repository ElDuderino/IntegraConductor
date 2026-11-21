"""Deterministic patch search and name resolution. No model inference involved."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from ..models import Patch
from .banks import normalize_expansion_name
from .database import normalize, tokens

# Words that describe the request rather than the sound.
_STOPWORDS = {"a", "an", "the", "sound", "sounds", "tone", "tones", "patch", "patches", "some"}

# Small, explicit vocabulary bridge from common musician terms to words Roland
# uses in names/categories. Matches made this way are labelled "alias".
QUERY_ALIASES: dict[str, tuple[str, ...]] = {
    "rhodes": ("tine", "stage", "rhodes"),
    "wurlitzer": ("wurly", "reed"),
    "wurli": ("wurly", "reed"),
    "ep": ("electric",),
    "epiano": ("electric", "ep"),
    "hammond": ("organ", "b3", "tw"),
    "b3": ("organ", "tw"),
    "upright": ("ac", "acoustic"),
    "fretless": ("fretls", "fretlss", "frtls"),
    "acoustic": ("ac",),
    "electric": ("e", "el", "ep"),
    "guitar": ("gtr", "gt"),
    "bass": ("bs",),
    "strings": ("str", "string"),
    "piano": ("pno", "grand"),
}


@dataclass(frozen=True)
class SearchHit:
    patch: Patch
    score: float
    match: str
    matched_tokens: int
    query_tokens: int
    aliases: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        out = self.patch.to_dict()
        out["score"] = round(self.score, 2)
        out["match"] = self.match
        if self.aliases:
            out["aliases"] = list(self.aliases)
        return out


def _passes_filters(p: Patch, kind, engine, category, expansion, bank) -> bool:
    if kind and p.kind != kind:
        return False
    if engine and (p.engine or "").casefold() != engine.casefold():
        return False
    if category and not any(
        normalize(category) in normalize(c) for c in (p.category, *p.alt_categories) if c
    ):
        return False
    if bank and normalize(bank) not in normalize(p.bank or ""):
        return False
    if expansion:
        want = expansion.casefold()
        if want in ("none", "builtin", "built-in", "factory"):
            return p.expansion_required is None
        if want == "any":
            return p.expansion_required is not None
        canonical = normalize_expansion_name(expansion) or expansion
        return (p.expansion_required or "").casefold() == canonical.casefold()
    return True


def _token_score(q: str, name_tokens: list[str], meta_tokens: set[str], fuzzy: bool):
    """Return (weight 0..1, label) for one query token."""
    best, label = 0.0, ""
    for t in name_tokens:
        if t == q:
            return 1.0, "name"
        if t.startswith(q) and best < 0.8:
            best, label = 0.8, "name"
        elif q in t and len(q) >= 3 and best < 0.6:
            best, label = 0.6, "name"
    if best:
        return best, label
    if q in meta_tokens:
        return 0.5, "category"
    if any(t.startswith(q) for t in meta_tokens if len(q) >= 3):
        return 0.45, "category"
    for alt in QUERY_ALIASES.get(q, ()):
        if alt in name_tokens or alt in meta_tokens:
            return 0.4, "alias"
    if fuzzy and len(q) >= 4:
        ratio = max(
            (SequenceMatcher(None, q, t).ratio() for t in name_tokens if len(t) >= 3),
            default=0.0,
        )
        if ratio >= 0.8:
            return 0.3 * ratio, "fuzzy"
    return 0.0, ""


def search(
    patches: list[Patch],
    query: str = "",
    *,
    kind: str | None = None,
    engine: str | None = None,
    category: str | None = None,
    expansion: str | None = None,
    bank: str | None = None,
    limit: int = 20,
    fuzzy: bool = True,
    aliases: dict[str, list[str]] | None = None,
) -> list[SearchHit]:
    aliases = aliases or {}
    q_norm = normalize(query)
    q_compact = q_norm.replace(" ", "")
    q_tokens = [t for t in tokens(query) if t not in _STOPWORDS] or tokens(query)

    hits: list[SearchHit] = []
    for p in patches:
        if not _passes_filters(p, kind, engine, category, expansion, bank):
            continue
        alias_names = tuple(aliases.get(p.id, ()))
        if not q_norm:
            hits.append(SearchHit(p, 0.0, "filter", 0, 0, alias_names))
            continue

        names = [p.name, *alias_names]
        norms = [normalize(n) for n in names]
        compacts = [n.replace(" ", "") for n in norms]
        if q_norm in norms or q_compact in compacts:
            hits.append(SearchHit(p, 100.0, "exact", len(q_tokens), len(q_tokens), alias_names))
            continue
        if any(c.startswith(q_compact) for c in compacts):
            hits.append(SearchHit(p, 90.0, "prefix", len(q_tokens), len(q_tokens), alias_names))
            continue
        if len(q_compact) >= 3 and any(q_compact in c for c in compacts):
            hits.append(
                SearchHit(p, 80.0, "substring", len(q_tokens), len(q_tokens), alias_names)
            )
            continue

        name_tokens = [t for n in names for t in tokens(n)]
        meta_tokens = set(
            tokens(
                " ".join(
                    x
                    for x in (p.category, *p.alt_categories, p.bank, p.engine, p.expansion_required)
                    if x
                )
            )
        )
        total, matched, labels = 0.0, 0, set()
        for q in q_tokens:
            weight, label = _token_score(q, name_tokens, meta_tokens, fuzzy)
            if weight:
                total += weight
                matched += 1
                labels.add(label)
        if not matched:
            continue
        score = 70.0 * total / len(q_tokens)
        if matched == len(q_tokens):
            match = "tokens" if labels <= {"name", "category"} else "+".join(sorted(labels))
        else:
            match = "partial"
        hits.append(SearchHit(p, score, match, matched, len(q_tokens), alias_names))

    hits.sort(key=lambda h: (-h.score, h.patch.name.casefold(), h.patch.id))
    return hits[:limit] if limit and limit > 0 else hits


def resolve_name(patches: list[Patch], name: str, aliases: dict[str, list[str]] | None = None):
    """Resolve a name to exactly one patch, or report candidates. Never guesses.

    Returns (patch, candidates): patch is set only for a single exact match, or
    failing that a single patch whose name contains the whole query.
    """
    hits = search(patches, name, limit=0, fuzzy=False, aliases=aliases)
    exact = [h for h in hits if h.match == "exact"]
    if len(exact) == 1:
        return exact[0].patch, []
    if len(exact) > 1:
        return None, exact
    strong = [h for h in hits if h.match in ("prefix", "substring")]
    if len(strong) == 1:
        return strong[0].patch, []
    return None, (strong or hits)[:10]
