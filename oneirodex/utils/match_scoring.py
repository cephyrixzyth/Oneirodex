"""Score IGDB name candidates and classify high vs low confidence."""

from difflib import SequenceMatcher
import re

from oneirodex.utils.fandom_alias import fandom_soft_score_boost

DEFAULT_HIGH_THRESHOLD = 0.92
DEFAULT_AMBIGUOUS_GAP = 0.08

# Cap when one alnum form is a digit-extended sequel of the other (RE vs RE2,
# Broken Sword vs Broken Sword 2). Keeps exact (1.0) clear of default gap 0.08.
_SEQUEL_ASYMMETRY_CAP = 0.85

_REMASTER_PACKAGING_RE = re.compile(
    r"\b(?:remastered|remake|hd|definitive|enhanced|director'?s?\s*cut|"
    r"anniversary|complete\s+edition|goty|game\s+of\s+the\s+year)\b",
    re.IGNORECASE,
)
_TRAILING_SEQUEL_TOKEN_RE = re.compile(
    r"\b(?:[2-9]|1[0-9]|II|III|IV|V|VI|VII|VIII|IX|X)\s*$",
    re.IGNORECASE,
)


# Multi-letter roman sequel numerals read as digits, so "Police Quest 3" and
# "Police Quest III" compare equal. Single I / V / X stay letters ("X-Wing").
_ROMAN_SEQUELS = {'ii': '2', 'iii': '3', 'iv': '4', 'vi': '6', 'vii': '7', 'viii': '8', 'ix': '9'}
_ROMAN_TOKEN_RE = re.compile(r'\b(ii|iii|iv|vi|vii|viii|ix)\b')


def normalize_for_score(name: str) -> str:
    """Lowercase alphanumeric-only form for similarity comparison."""
    if not name:
        return ''
    lowered = _ROMAN_TOKEN_RE.sub(lambda m: _ROMAN_SEQUELS[m.group(1)], name.lower())
    return re.sub(r'[^a-z0-9]+', '', lowered)


def _sequel_asymmetry_cap(left: str, right: str, score: float) -> float:
    """
    Demote digit-extended sequel siblings so exact titles clear the ambiguous gap.

    `residentevil` vs `residentevil2` and `brokensword` vs `brokensword2` otherwise
    sit at ~0.96 — within default gap 0.08 of an exact 1.0 hit.
    """
    if not left or not right or left == right:
        return score
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    if not longer.startswith(shorter) or len(longer) == len(shorter):
        return score
    rest = longer[len(shorter) :]
    if rest and rest[0].isdigit():
        return min(float(score), _SEQUEL_ASYMMETRY_CAP)
    return score


def _letter_suffix_cap(left: str, right: str, score: float) -> float:
    """A title that only adds one or two letters is a different word, not a match.

    ``stargaze``/``stargazer``, ``masterpiece``/``masterpieced`` and
    ``slimelab``/``slimelabs`` sit above the 0.92 threshold on similarity
    alone; they go to review instead of auto-matching (2026-11-21 scan review).
    """
    if not left or not right or left == right:
        return score
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    rest = longer[len(shorter):]
    if longer.startswith(shorter) and 1 <= len(rest) <= 2 and rest.isalpha():
        return min(float(score), _SEQUEL_ASYMMETRY_CAP)
    return score


def _primary_head_remaster_score(cleaned_name: str, candidate_name: str) -> float:
    """
    W21-BE-3 — treat remaster/subtitle packaging as an exact hit when the
    candidate's primary head equals the cleaned folder label.

    Safe cases (score 1.0):
    - Hyphen remaster tails: `Broken Sword 2 - the Smoking Mirror: Remastered`
    - Colon/emdash tails that include remaster/edition packaging tokens
    - Colon tails when the head already carries a sequel token (II / 2 / …)

    Not boosted: bare alternate games like `Chasm: The Rift` vs folder `Chasm`.
    """
    folder = (cleaned_name or '').strip()
    store = (candidate_name or '').strip()
    if not folder or not store:
        return 0.0
    folder_norm = normalize_for_score(folder)
    if not folder_norm:
        return 0.0

    for sep in (' - ', ': ', ' — ', ' – '):
        if sep not in store:
            continue
        head, rest = store.split(sep, 1)
        head = head.strip()
        rest = rest.strip()
        if not head or not rest:
            continue
        if normalize_for_score(head) != folder_norm:
            continue
        if sep == ' - ':
            return 1.0
        if _REMASTER_PACKAGING_RE.search(rest):
            return 1.0
        if _TRAILING_SEQUEL_TOKEN_RE.search(head):
            return 1.0
        # First separator only — do not keep peeling into unrelated subtitles.
        break
    return 0.0


def _pair_score(cleaned_name: str, candidate_name: str) -> float:
    """Score one cleaned label against one candidate title (no steam bump)."""
    left = normalize_for_score(cleaned_name)
    right = normalize_for_score(candidate_name)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0

    score = float(SequenceMatcher(None, left, right).ratio())
    score = max(score, _primary_head_remaster_score(cleaned_name, candidate_name))
    # BE-DET-9 — soft alias / regional / remaster registry boost for ranking.
    # Identify must still force propose-only on soft hits (never invent IGDB ids).
    score = max(score, fandom_soft_score_boost(cleaned_name, candidate_name))
    score = _sequel_asymmetry_cap(left, right, score)
    score = _letter_suffix_cap(left, right, score)
    return float(score)


def score_candidate(cleaned_name: str, candidate_name: str, *, steam_title: str | None = None) -> float:
    """
    Return similarity score in [0, 1] between cleaned folder name and an IGDB candidate title.

    Optional steam_title: when provided, score is the max of (folder vs candidate)
    and (steam_title vs candidate) — the resolved Steam title is often a cleaner
    match than the raw folder label.

    W21-BE-3 edges (threshold stays ≥0.92): remaster/subtitle primary-head peel,
    sequel digit-asymmetry cap, exact alnum short-circuit.
    """
    score = _pair_score(cleaned_name, candidate_name)

    if steam_title:
        steam_score = _pair_score(steam_title, candidate_name)
        score = max(score, steam_score)

    return float(score)


def classify_confidence(
    scores: list[float],
    *,
    high_threshold: float = DEFAULT_HIGH_THRESHOLD,
    ambiguous_gap: float = DEFAULT_AMBIGUOUS_GAP,
) -> str:
    """
    Classify match confidence from a sorted-or-unsorted list of candidate scores.

    high: best >= threshold AND (only one score OR best-second >= gap)
    low: otherwise
    """
    if not scores:
        return "low"

    ordered = sorted((float(s) for s in scores), reverse=True)
    best = ordered[0]
    if best < high_threshold:
        return "low"
    if len(ordered) == 1:
        return "high"
    if (best - ordered[1]) >= ambiguous_gap:
        return "high"
    return "low"


def _collapse_equivalent_scores(
    scored: list[tuple[float, dict]],
) -> list[tuple[float, dict]]:
    """
    Collapse candidates that normalize to the same alnum title (e.g. `1000x Resist`
    vs `1000xRESIST`) so identical spelling variants do not fake an ambiguous gap.
    Keeps the first (highest-score) representative per normalized key.
    """
    seen: set[str] = set()
    out: list[tuple[float, dict]] = []
    for score, candidate in scored:
        key = normalize_for_score(candidate.get('name') or '')
        if not key:
            out.append((score, candidate))
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append((score, candidate))
    return out


def select_best_match(
    cleaned_name: str,
    candidates: list[dict],
    *,
    steam_title: str | None = None,
    high_threshold: float | None = None,
    ambiguous_gap: float | None = None,
):
    """
    Rank IGDB candidate dicts (must include 'name') and return (best_or_None, confidence).

    On high confidence, best is the winning candidate dict.
    On low confidence, best is None (caller should queue for human review).

    Thresholds default to module constants; callers may pass GlobalSettings-backed
    values from resolve_scan_match_policy (W20-4).
    """
    if not candidates:
        return None, "low"

    thr = DEFAULT_HIGH_THRESHOLD if high_threshold is None else float(high_threshold)
    gap = DEFAULT_AMBIGUOUS_GAP if ambiguous_gap is None else float(ambiguous_gap)

    scored = []
    for candidate in candidates:
        name = candidate.get('name') or ''
        scored.append((score_candidate(cleaned_name, name, steam_title=steam_title), candidate))

    scored.sort(key=lambda item: item[0], reverse=True)
    for_gap = _collapse_equivalent_scores(scored)
    # An exact title wins over its own subtitled variants ("Jagged Alliance 2"
    # vs "Jagged Alliance 2: Wildfire"): the head boost lifts those to 1.0 too,
    # which would otherwise read as a tie. Only one distinct exact title counts.
    wanted = {normalize_for_score(cleaned_name), normalize_for_score(steam_title or '')} - {''}
    exact = [
        (score, candidate) for score, candidate in for_gap
        if normalize_for_score(candidate.get('name') or '') in wanted
    ]
    if len(exact) == 1 and exact[0][0] >= thr:
        return exact[0][1], "high"
    # A folder that does not say "Remastered" (or HD, Definitive, ...) means the
    # original release: when the remaster ties it, the remaster steps aside.
    if not _REMASTER_PACKAGING_RE.search(cleaned_name or ''):
        plain = [
            (score, candidate) for score, candidate in for_gap
            if not _REMASTER_PACKAGING_RE.search(candidate.get('name') or '')
        ]
        if plain and len(plain) < len(for_gap) and classify_confidence(
            [score for score, _ in for_gap], high_threshold=thr, ambiguous_gap=gap,
        ) != "high" and classify_confidence(
            [score for score, _ in plain], high_threshold=thr, ambiguous_gap=gap,
        ) == "high":
            return plain[0][1], "high"
    confidence = classify_confidence(
        [s for s, _ in for_gap],
        high_threshold=thr,
        ambiguous_gap=gap,
    )
    if confidence == "high":
        return scored[0][1], "high"
    return None, "low"


def rank_candidates(cleaned_name: str, candidates: list[dict], *, steam_title: str | None = None) -> list[dict]:
    """Return candidates annotated with 'match_score', best first (for review UI)."""
    ranked = []
    for candidate in candidates:
        entry = dict(candidate)
        entry['match_score'] = score_candidate(
            cleaned_name, candidate.get('name') or '', steam_title=steam_title
        )
        ranked.append(entry)
    ranked.sort(key=lambda c: c['match_score'], reverse=True)
    return ranked
