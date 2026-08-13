"""Deterministic guardrails.

Voice turns cannot afford an extra model round-trip per check, so these are pattern
based: fast, testable, and identical every run — which is what makes them provable in
the Golden Dataset. They are the outer layer only; the real access-control boundary is
the tool layer, which refuses regardless of what the model was persuaded to say.
"""
import re
from dataclasses import dataclass

MEDICAL_ADVICE_PATTERNS = [
    r"\b(is|could|might)\s+(this|it|that)\s+(be\s+)?(cancer|melanoma|malignant|serious|infected)",
    r"\bshould i (be worried|worry|be concerned|stop taking|start taking|take)\b",
    r"\b(what|which)\s+(medication|medicine|drug|cream|ointment|dose|dosage)\s+(should|do)\b",
    r"\b(diagnose|diagnosis)\b",
    r"\bdo i have\b.*\b(cancer|infection|rash|condition|disease)\b",
    r"\bis (this|it) (normal|dangerous|contagious)\b",
    r"\bhow (do|can) i treat\b",
    r"\bcan i (stop|skip|double)\s+(my|the)\s+(medication|dose|prescription)\b",
]

INJECTION_PATTERNS = [
    r"\bignore (all |any |your )?(previous|prior|earlier|above)\s+(instructions?|prompts?|rules?)",
    r"\bdisregard (all |any |your )?(previous|prior|the)\s+(instructions?|rules?)",
    r"\b(reveal|show|print|repeat|output)\s+(me\s+)?(your|the)\s+(system\s+)?(prompt|instructions|rules)",
    r"\byou are now\b",
    r"\bnew (system )?instructions?\b[:\s]",
    r"\bpretend (you are|to be)\b",
    r"\bdeveloper mode\b",
    r"\boverride\s+(your|the)\s+(rules|policy|restrictions)",
    r"\b(act|behave) as (if you are |an? )?(admin|administrator|developer|root)",
]

# Requests that belong to a different clinic workflow than the one Maya owns.
OUT_OF_SCOPE_PATTERNS = [
    r"\b(refill|renew)\s+(my\s+)?(prescription|medication|script)",
    r"\bprior authorization\b",
    r"\b(pay|paying|payment|bill|invoice|balance|charge)\b.*\b(card|account|owe|due)\b",
    r"\bmy (lab|test|biopsy) results?\b",
]

EMERGENCY_PATTERNS = [
    r"\b(chest pain|can'?t breathe|cannot breathe|trouble breathing|unconscious|suicidal|kill myself|overdose|anaphyla|severe bleeding|bleeding heavily)\b",
]

MEDICAL_DEFLECTION = (
    "I'm not able to give medical advice — I'm the scheduling assistant. "
    "What I can do is book you in with one of our dermatologists, or pass a message "
    "to the clinical team. Would either of those help?"
)

EMERGENCY_DEFLECTION = (
    "That sounds like it may need urgent attention. Please hang up and call 911, or go "
    "to your nearest emergency room. I can't help with medical emergencies here."
)

INJECTION_DEFLECTION = (
    "I can only help with appointments and clinic information. Would you like to book, "
    "change, or cancel a visit?"
)

# Claiming to be staff, or asking after a named third party's records, is the shape of a
# social-engineering attempt. Identity comes from Verification and nothing else.
IDENTITY_CLAIM_PATTERNS = [
    r"\bi'?m (actually |really )?(a |an )?(nurse|doctor|physician|staff|admin|administrator|receptionist)\b",
    r"\b(act|acting) as (an? )?(admin|administrator|staff|nurse|doctor)\b",
    r"\bon behalf of\b.*\bpatient\b",
    r"\b(read|tell|give) me\b.*\b[A-Z][a-z]+ [A-Z][a-z]+'?s?\b.*\b(appointment|record|file|number)",
]

IDENTITY_CLAIM_DEFLECTION = (
    "I'm not able to share anyone else's appointment details, and I can't take instructions "
    "to work with different permissions — I can only verify the person I'm speaking with. "
    "I'm happy to help with your own visit. Would you like to book or change one?"
)

OUT_OF_SCOPE_DEFLECTION = (
    "That one's outside what I can handle — I look after appointments and general clinic "
    "questions. I can pass a message to the staff, or book you a visit. Which would you prefer?"
)


@dataclass
class GuardVerdict:
    triggered: bool
    kind: str | None = None
    reply: str | None = None
    escalate_reason: str | None = None


def _matches(text: str, patterns: list[str]) -> bool:
    lowered = text.lower()
    return any(re.search(p, lowered) for p in patterns)


def check_input(text: str) -> GuardVerdict:
    """Screen a caller turn before the model sees it."""
    if _matches(text, EMERGENCY_PATTERNS):
        return GuardVerdict(True, "emergency", EMERGENCY_DEFLECTION, "possible_emergency")
    if _matches(text, IDENTITY_CLAIM_PATTERNS):
        return GuardVerdict(True, "identity_claim", IDENTITY_CLAIM_DEFLECTION)
    if _matches(text, INJECTION_PATTERNS):
        return GuardVerdict(True, "prompt_injection", INJECTION_DEFLECTION)
    if _matches(text, MEDICAL_ADVICE_PATTERNS):
        return GuardVerdict(True, "medical_advice", MEDICAL_DEFLECTION, "medical_question")
    if _matches(text, OUT_OF_SCOPE_PATTERNS):
        return GuardVerdict(True, "out_of_scope", OUT_OF_SCOPE_DEFLECTION, "out_of_scope_request")
    return GuardVerdict(False)


DIAGNOSTIC_CLAIM_PATTERNS = [
    r"\byou (probably |likely |may |might )?have\b.*\b(cancer|melanoma|infection|eczema|psoriasis)\b",
    r"\bit'?s (probably|likely|definitely) (benign|malignant|cancer|nothing serious)\b",
    r"\bi (would |'d )?recommend (taking|applying|using)\b.*\b(cream|steroid|antibiotic|medication)\b",
    r"\byou should (take|apply|use|stop)\b.*\b(medication|cream|steroid|antibiotic|dose)\b",
]


def check_output(text: str) -> GuardVerdict:
    """Screen Maya's reply before it is spoken."""
    if _matches(text, DIAGNOSTIC_CLAIM_PATTERNS):
        return GuardVerdict(True, "medical_advice_output", MEDICAL_DEFLECTION, "medical_question")
    return GuardVerdict(False)


def sanitise_retrieved(text: str) -> str:
    """Neutralise instruction-shaped text arriving from retrieved documents, so a
    poisoned FAQ entry cannot redirect the agent."""
    if _matches(text, INJECTION_PATTERNS):
        return "[clinic document omitted: contained instruction-like content]"
    return text
