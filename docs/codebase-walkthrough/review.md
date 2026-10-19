# Readiness checkpoint

Answer without looking below:

1. Why can a Caller ask clinic hours without Verification?
2. Which container should prevent two Patients from booking the same Slot, and why?
3. What internal path does Domain receive for `/api/domain/slots?limit=2`?
4. What evidence proves Gateway stripped the public prefix?
5. Why does `limit=201` return `422` without querying PostgreSQL?
6. Why does changing `maya.role` to `admin` not grant backend Admin privileges?
7. Why does the claim request not accept a `user_id` or `patient_id` chosen by the browser?
8. Why does call history not accept a `patient_id`, and what prevents duplicate Feedback?

## Answers

1. Clinic hours are public information and do not access a Patient record, so the Caller does not need to prove a Patient identity.
2. Domain owns the rule because booking is an authoritative state transition requiring a database row lock, conflict check, and transaction. Agent may request the operation but cannot guarantee it is legal.
3. Domain receives `/slots?limit=2`; Gateway removes `/api/domain` and preserves the query string.
4. Gateway logs the public path, Domain logs `/slots`, and the matching request ID connects both entries to the same request.
5. The route exists, but FastAPI validates the `le=200` constraint before calling the handler. Because the handler never starts, it cannot construct or execute SQL.
6. The local-storage role controls React navigation only. Backend services decode and verify the signed JWT and enforce the trusted role themselves.
7. Domain derives `user_id` from the signed JWT and identifies the Patient by a server-side phone-and-DOB match. Accepting either identifier directly from the browser would let a caller attempt to claim someone else's identity.
8. Domain derives the current Patient from the signed token and filters Calls by that trusted identity. It checks for existing Feedback to return a clear `409`, while the unique constraint on `feedback.call_id` provides the final database-level guarantee.

---

# Go deeper — Interview preparation

## Why separate Agent from Domain?

Agent performs probabilistic interpretation: it decides what the Caller means, which tool fits, and how Maya should reply. Domain performs deterministic authorization and state changes: it checks identity, locks rows, enforces clinic rules, and commits records. This prevents an LLM mistake or prompt injection from overriding business invariants.

## Why have both `maya.token` and `maya.role`?

The token is signed authorization evidence sent to backend services. The separate role is an easily read UI hint used to select routes without decoding the JWT in the browser. This duplicates a small amount of state for convenience, so backend code must never treat the local-storage role as authoritative.

## What is the closest misleading explanation of a `404`?

"Nginx returned it because the response says `Server: nginx`." Nginx may merely proxy an upstream response. The correct procedure is to correlate paths, timestamps, request IDs, and service logs to find the first rejecting layer.

## What state changes during login?

The browser gains local-storage and React state. Auth reads the User row and verifies its hash but does not change database state. The server does not create a traditional session row; the signed JWT carries the portal identity until expiration.

## Why keep Auth User and Domain Patient separate?

An account is a login credential and role; a Patient is a clinic record that may exist before anyone creates a portal account. Keeping them separate allows seeded or imported clinic records to remain unclaimed, then be linked later without placing password concerns inside the scheduling domain. The current implementation stores the Auth User ID as an integer rather than a cross-service database foreign key, preserving service ownership at the cost of application-level consistency checks.

# Final practice order

1. Define Caller, Patient, Verification, Authentication, Slot, Appointment, and Approval Task without opening `CONTEXT.md`.
2. Draw the six containers and label every HTTP or SQL connection.
3. Predict and run one valid public Slot request.
4. Match its response ID to Gateway and Domain evidence.
5. Trigger one `404` and one `422`, then name the first rejecting mechanism.
6. Trace login from `Login.tsx` to JWT storage and role routing.
7. Trace `sub` from a signed JWT through `/patients/claim` into `patients.user_id`.
8. Trace one history card from `Call`, `CallSummary`, and `Feedback` rows into `CallOut`.
9. Continue with Patient identity security.
