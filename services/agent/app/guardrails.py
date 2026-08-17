"""Deterministic guardrails.

Voice turns cannot afford an extra model round-trip per check, so these are pattern
based: fast, testable, and identical every run — which is what makes them provable in
the Golden Dataset. They are the outer layer only; the real access-control boundary is
the tool layer, which refuses regardless of what the model was persuaded to say.
"""
import re
from dataclasses import dataclass

MEDICAL_ADVICE_PATTERNS = [
    # "is this cancer", "could that be melanoma", "is this mole cancerous"
    r"\b(is|could|might)\s+(this|it|that|my \w+)\s+(be\s+)?(cancer|cancerous|melanoma|malignant|serious|infected)\b",
    r"\b(is|could|might)\s+(this|that|it)\s+(mole|spot|rash|bump|lump)\s+(be\s+)?(cancer|cancerous|melanoma|malignant|serious|infected)\b",
    r"\bshould i (be worried|worry|be concerned|stop taking|start taking|keep taking)\b",
    # "should I take X" only when X is a medicine, never "should I take the Thursday slot"
    r"\bshould i take\b(?!.*\b(slot|time|appointment|opening|spot|one)\b).*\b(pill|pills|tablet|medication|medicine|drug|antibiotic|cream|dose|steroid|ibuprofen|tylenol|benadryl)\b",
    r"\b(what|which)\s+(pill|medication|medicine|drug|cream|ointment|dose|dosage)\s+(should|do|can)\b",
    r"\bdiagnose\b",
    r"\bwhat('?s| is) (my|the) diagnosis\b",
    # "do I have an infection" — not "do I have an appointment for my rash"
    r"\bdo i have (a |an )?(skin )?(cancer|infection|rash|condition|disease|melanoma)\b",
    r"\bis (this|it|that) (dangerous|contagious|infected)\b",
    r"\bis (this|it|that) normal\b(?! (to|for) (wait|book|schedule|call|take|get|be seen))",
    r"\bhow (do|can|should) i treat\b",
    r"\bcan i (stop|skip|double)\s+(my|the)\s+(medication|dose|prescription)\b",
]

INJECTION_PATTERNS = [
    r"\bignore (all |any |your )?(previous|prior|earlier|above)\s+(instructions?|prompts?|rules?)",
    r"\bdisregard (all |any |your )?(previous|prior|the)\s+(instructions?|rules?)",
    r"\b(reveal|show|print|repeat|output)\s+(me\s+)?(your|the)\s+(system\s+)?(prompt|instructions|rules)",
    r"\byou are now\b",
    # An instruction block, not "my doctor gave me new instructions to book a follow-up"
    r"\bnew (system )?instructions?\s*:",
    r"\b(here are|follow these|these are) (your |the |my )?new (system )?instructions\b",
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
    # Asking for results is staff work; booking a visit *about* results is Maya's job.
    r"^(?!.*\b(book|schedule|appointment|follow-up|follow up|visit|come in)\b).*\bmy (lab|test|biopsy) results?\b",
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
    # Claiming a staff role to get at records — not a nurse booking her own skin check.
    r"^(?!.*\b(myself|my own|for me|my appointment|my visit)\b).*\bi'?m (actually |really )?(a |an |the )?(nurse|doctor|physician|staff|admin|administrator|receptionist)\b",
    r"\b(act|acting) as (an? )?(admin|administrator|staff|nurse|doctor)\b",
    r"\bon behalf of\b.*\bpatient\b",
]

# Asking after a *named* third party's records. Matched against the raw text because the
# capitalised name is the signal — lower-cased, "tell me my next appointment" would trip it.
THIRD_PARTY_RECORD_PATTERNS = [
    r"\b(read|tell|give|show)\s+me\b.*\b[A-Z][a-z]+ [A-Z][a-z]+'?s?\b.*\b(appointment|record|file|number|schedule)",
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


def _matches(text: str, patterns: list[str], *, case_sensitive: bool = False) -> bool:
    haystack = text if case_sensitive else text.lower()
    return any(re.search(p, haystack) for p in patterns)


def check_input(text: str) -> GuardVerdict:
    """Screen a caller turn before the model sees it."""
    if _matches(text, EMERGENCY_PATTERNS):
        return GuardVerdict(True, "emergency", EMERGENCY_DEFLECTION, "possible_emergency")
    if _matches(text, IDENTITY_CLAIM_PATTERNS) or _matches(
        text, THIRD_PARTY_RECORD_PATTERNS, case_sensitive=True
    ):
        return GuardVerdict(True, "identity_claim", IDENTITY_CLAIM_DEFLECTION)
    if _matches(text, INJECTION_PATTERNS):
        return GuardVerdict(True, "prompt_injection", INJECTION_DEFLECTION)
    if _matches(text, MEDICAL_ADVICE_PATTERNS):
        return GuardVerdict(True, "medical_advice", MEDICAL_DEFLECTION, "medical_question")
    if _matches(text, OUT_OF_SCOPE_PATTERNS):
        return GuardVerdict(True, "out_of_scope", OUT_OF_SCOPE_DEFLECTION, "out_of_scope_request")
    return GuardVerdict(False)


# Diagnostic phrasing only. "You have a follow-up for your eczema" is a booking
# confirmation and must be sayable — the condition word alone is not the signal.
DIAGNOSTIC_CLAIM_PATTERNS = [
    r"\byou (probably|likely|may|might|definitely|do) have\b(?!.*\b(appointment|visit|follow-up|booked|scheduled)\b).*\b(cancer|melanoma|infection|eczema|psoriasis)\b",
    r"\byou have (a |an )?(skin |bacterial |fungal |viral )?(cancer|melanoma|infection|eczema|psoriasis)\b",
    r"\bit'?s (probably|likely|definitely) (benign|malignant|cancer|nothing serious)\b",
    r"\bi('d| would)? recommend (taking|applying|using)\b.*\b(cream|steroid|antibiotic|medication|hydrocortisone)\b",
    r"\byou should (take|apply|use|stop|start) (the |your |a |an |some |this )?(\w+ )?(medication|cream|steroid|antibiotic|dose|ointment|prescription)\b",
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
