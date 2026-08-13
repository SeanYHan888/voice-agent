# Patient Access Voice Agent

An AI voice agent that answers a medical clinic's phone line and web voice widget to handle appointment scheduling, answer clinic FAQs, and escalate to humans — modeled on Assort Health's patient-access product, built against a mock clinic.

## Language

### Actors

**Caller**:
A party on a live voice conversation whose identity has not yet been verified.
_Avoid_: user, customer

**Patient**:
A person with a patient record at the clinic — the identity a Caller can prove to be, and a role in the web portal.
_Avoid_: user, client, customer

**Admin**:
A staff operator who reviews escalations, approves gated actions, and analyzes operations in the dashboard.
_Avoid_: staff, operator, user

**Maya**:
The voice agent's persona — the name it introduces itself with on every Call.
_Avoid_: the bot, the assistant, the AI

### Identity

**Verification**:
Proving that a Caller is a specific Patient during a voice conversation.
_Avoid_: authentication, login

**Authentication**:
Signing into the web portal as a Patient or Admin.
_Avoid_: verification

### Conversation

**Call**:
A single voice conversation between a Caller and the agent, regardless of transport (phone or browser widget).
_Avoid_: session, chat

**Call Summary**:
The AI-written digest of a finished Call, tagged with intent and sentiment.
_Avoid_: transcript (that's the raw text, not the digest)

**Escalation**:
Handing a conversation the agent cannot or must not handle to a human, creating work for an Admin.
_Avoid_: transfer, handoff

**Feedback**:
A Patient's rating (1–5 stars plus optional comment) of a Call.
_Avoid_: review, survey

### Scheduling

**Provider**:
A clinician at the clinic who has a schedule Patients can book against.
_Avoid_: doctor, physician, resource

**Visit Type**:
The category of an Appointment that determines its duration (New Patient 30 min, Follow-up 15 min).
_Avoid_: appointment type, service

**Slot**:
A bookable time on a Provider's calendar, not yet claimed by an Appointment.
_Avoid_: opening, availability

**Appointment**:
A Slot claimed by a Patient for a Visit Type.
_Avoid_: booking, visit

**Approval Task**:
Work queued for an Admin's sign-off before a gated action executes — e.g. a cancellation or reschedule within 24 hours of the Appointment.
_Avoid_: approval request, review item
