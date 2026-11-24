"""NLP requirement-candidate adapter (plan phase 2, design §5.4).

The adapter output is an UNTRUSTED requirement candidate, never an effective requirement or a
publication request. This module turns a candidate into a ``design-requirement`` candidate under
a two-layer acceptance rule:

  1. Deterministic conversions (registered numerals / orientation enums / measured values) are
     re-verified by TRUSTED rules against the host-provided source span — the model does not
     self-certify. A verified user-stated/image-observed claim keeps its strength and records a
     conversion evidence entry.
  2. Complex semantics (relations, negation, comparison, role ambiguity) and any claim whose span
     does not deterministically match stay TENTATIVE: they become soft conditions plus an open
     question for explicit user confirmation, and never drive irreversible exclusion or publish.

``author-proposed`` claims never become confirmed hard requirements. Schema/locator failures get
a bounded repair budget (first version: at most 2 repairs); exhaustion returns a structural error,
never infinite regeneration. NLP vocabulary stays in this input-adaptation layer; it never enters
geometry, rendering or the generic security kernel, and grants no approval.
"""
from __future__ import annotations

import re
from typing import Any, Callable

from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry

MAX_REPAIRS = 2

# Trusted deterministic numeral vocabulary (Chinese / English / Arabic). A count claim is only
# confirmed when the source span actually contains a numeral equal to the claimed value.
_NUMERALS = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
}
_ORIENTATION = {
    "landscape": ("横向", "横版", "landscape", "horizontal"),
    "portrait": ("纵向", "竖版", "portrait", "vertical"),
}
_MEASURE_UNITS = ("mm", "毫米")


def validate_candidate(candidate: dict[str, Any], source_text: str,
                       registry: SchemaRegistry | None = None) -> dict[str, Any]:
    """Closed-world validation + real source-span existence (design §5.4).

    Rejects unknown fields (publish/approval/library/tool), duplicate claim IDs, out-of-bounds or
    inverted locators, and open questions referencing unknown conditions. The locator must index
    the host-provided source text by Unicode code point; a fabricated span fails closed.
    """
    registry = registry or SchemaRegistry()
    registry.validate("nlp-requirement-candidate", candidate)
    seen: set[str] = set()
    for claim in candidate["claims"]:
        cid = claim["id"]
        if cid in seen:
            raise ProtocolError("NLP_CLAIM_DUPLICATE", cid)
        seen.add(cid)
        loc = claim["source_locator"]
        start, end = loc["start"], loc["end"]
        if start >= end or end > len(source_text):
            raise ProtocolError("NLP_LOCATOR_OUT_OF_BOUNDS", cid)
    for question in candidate.get("open_questions", []):
        unknown = set(question["condition_ids"]) - seen
        if unknown:
            raise ProtocolError("NLP_QUESTION_UNKNOWN_CONDITION", ",".join(sorted(unknown)))
    return candidate


def _verify_claim(claim: dict[str, Any], span: str) -> tuple[bool, str | None]:
    """Trusted deterministic re-verification of a claim against its source span.

    Returns (verified, rule). Only measure/enum/count have first-version trusted rules; relation
    and any non-matching span stay unverified (tentative). This never trusts origin/confidence.
    """
    pred = claim["predicate"]
    kind = pred["kind"]
    if kind == "count":
        value = pred["value"]
        if any(token in span for token, n in _NUMERALS.items() if n == value):
            return True, "numeral-word"
        if any(int(m) == value for m in re.findall(r"\d+", span)):
            return True, "numeral-digit"
        return False, None
    if kind == "enum":
        tokens = _ORIENTATION.get(pred["value"], ())
        if any(token in span for token in tokens):
            return True, "orientation-enum"
        return False, None
    if kind == "measure":
        value = pred["value"]
        numeral = str(int(value)) if float(value).is_integer() else str(value)
        if numeral in span and any(unit in span for unit in _MEASURE_UNITS):
            return True, "measure-value-unit"
        return False, None
    return False, None


def normalize_candidate(candidate: dict[str, Any], source_text: str, *,
                        requirement_id: str, object_scope: str,
                        registry: SchemaRegistry | None = None) -> dict[str, Any]:
    """Convert a verified candidate into a design-requirement candidate (two-layer acceptance).

    Confirmed claims (trusted-rule verified, not author-proposed) keep their strength; everything
    else becomes a soft condition plus a confirmation open question. The result is a candidate
    requirement, not a confirmed user requirement: tentative conditions never prove full
    satisfaction or drive publication. Returns {requirement, tentative, conversion_evidence}.
    """
    registry = registry or SchemaRegistry()
    validate_candidate(candidate, source_text, registry)
    conditions: list[dict[str, Any]] = []
    open_questions: list[dict[str, Any]] = []
    tentative: list[str] = []
    evidence: list[dict[str, Any]] = []
    for claim in candidate["claims"]:
        loc = claim["source_locator"]
        span = source_text[loc["start"]:loc["end"]]
        verified, rule = _verify_claim(claim, span)
        confirmed = verified and claim["origin"] != "author-proposed"
        strength = claim["strength"] if confirmed else "soft"
        conditions.append({"id": claim["id"], "strength": strength,
                           "predicate": claim["predicate"], "source_ref": candidate["source_ref"]})
        if confirmed:
            evidence.append({"claim_id": claim["id"], "span": span, "rule": rule,
                             "value": claim["predicate"].get("value")})
        else:
            tentative.append(claim["id"])
            open_questions.append({
                "id": f"q-{claim['id']}",
                "question": f"Condition '{claim['id']}' needs explicit user confirmation "
                            f"(origin={claim['origin']}, trusted_rule={rule}).",
                "blocks": "creation"})
    requirement = {"schema_version": 1, "requirement_id": requirement_id, "revision": 1,
                   "object_scope": object_scope, "conditions": conditions}
    if open_questions:
        requirement["open_questions"] = open_questions
    registry.validate("design-requirement", requirement)
    return {"requirement": requirement, "tentative": tentative, "conversion_evidence": evidence}


def adapt_with_retry(generate: Callable[[int], dict[str, Any]], source_text: str, *,
                     max_repairs: int = MAX_REPAIRS,
                     registry: SchemaRegistry | None = None) -> dict[str, Any]:
    """Bounded repair loop for JSON/Schema failures (design §5.4: at most 2 repairs).

    ``generate(attempt)`` produces a candidate; each is validated closed-world against the source.
    A structural failure consumes one repair; exhaustion raises NLP_ADAPTATION_FAILED rather than
    regenerating forever. Repair only fixes format/interpretation, never the user's original intent.
    """
    registry = registry or SchemaRegistry()
    attempt = 0
    while True:
        candidate = generate(attempt)
        try:
            return validate_candidate(candidate, source_text, registry)
        except ProtocolError:
            if attempt >= max_repairs:
                raise ProtocolError("NLP_ADAPTATION_FAILED", f"repairs exhausted ({max_repairs})")
            attempt += 1