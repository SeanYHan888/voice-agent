# Lesson 7 — Account-to-Patient Linking

## 7. Account-to-Patient linking

**Definition:** Account-to-Patient linking writes the authenticated portal User ID onto exactly one matching clinic Patient record, allowing future requests from that account to resolve a server-controlled Patient identity.

Authentication answers:

```shell
Which portal User signed in?
```

Linking answers a different question:

```shell
Which clinic Patient record belongs to that User?
```

The records are intentionally separate:

```shell
Auth User
  id, email, password_hash, role

Domain Patient
  id, name, dob, phone, user_id?
```

A newly registered portal User has no Patient link yet. When `/portal` loads, React requests `GET /api/domain/patients/me`. Domain verifies the JWT, reads its `sub` claim as the Auth User ID, and looks for a Patient whose `user_id` matches. If none exists, Domain returns `404`, and React displays the linking form.

The form submits:

```http
POST /api/domain/patients/claim
Authorization: Bearer <signed portal JWT>
Content-Type: application/json

{
  "phone": "555-010-0104",
  "dob": "1996-01-09"
}
```

Domain processes the claim in this order:

1. Decode and verify the JWT.
2. Require the trusted token role to be `patient`.
3. Normalize the submitted phone number to its stored form.
4. Find a Patient by normalized phone number.
5. Require the date of birth to match too.
6. Refuse a record already linked to a different User.
7. Set `patient.user_id = principal.user_id`.
8. Commit the change and return `PatientOut`.

The status branches are deliberate:

| Status | Cause |
|---|---|
| `401` | Missing, expired, or invalid JWT |
| `403` | Authenticated account is not a Patient-role account |
| `404` | Phone and date of birth do not identify a record |
| `409` | The matching record belongs to another portal User |
| `200` | The link was created or already belonged to this User |

Only one persistent field changes:

```shell
Before: patients.user_id = null
After:  patients.user_id = <JWT sub>
```

The JWT is not replaced and does not gain a `patient_id`. On each later request, Domain uses the signed `sub` to resolve the current Patient mapping from its own database. That keeps Patient identity under server control.

### Code example — Normalize the phone lookup key

**Predict first:** Predict all three printed strings and decide which two inputs become identical.

```python
def normalize_phone(raw: str) -> str:
    digits = "".join(character for character in raw if character.isdigit())
    if len(digits) == 10:
        digits = f"1{digits}"
    return f"+{digits}"

print(normalize_phone("555-010-0104"))
print(normalize_phone("(555) 010 0104"))
print(normalize_phone("+1 555 010 0104"))

assert normalize_phone("555-010-0104") == "+15550100104"
assert normalize_phone("(555) 010 0104") == "+15550100104"
```

**Trace it:** The function discards non-digits, prepends the US country code when exactly ten digits remain, and adds the leading `+`. The database query therefore compares one canonical representation rather than every possible human formatting style.

**What to notice:** Normalization improves matching, but authorization still depends on the verified JWT and both submitted identity fields—not on phone formatting alone.

**Try changing:** Pass a nine-digit value and identify the validation gap: this helper normalizes characters but does not prove the result is a valid telephone number.

### Integration example — Follow the User ID from login to Patient access

**Predict first:** If the JWT contains `sub="42"` and the matching Patient starts with `user_id=null`, predict which value is stored and whether the original JWT changes.

```python
jwt_claims = {"sub": "42", "role": "patient"}
patient = {"id": 7, "user_id": None}

principal_user_id = int(jwt_claims["sub"])
patient["user_id"] = principal_user_id

print(patient)
print(jwt_claims)

assert patient == {"id": 7, "user_id": 42}
assert "patient_id" not in jwt_claims
```

**Trace it:** Auth previously signed `sub="42"`. Domain converts it to integer User ID `42`, writes that value into the matching Patient row, and leaves the token payload unchanged. A later `/patients/me` request repeats the server-side lookup `Patient.user_id == 42`.

**What to notice:** The link is durable database state. The browser cannot select an arbitrary `patient_id`, because the claim request accepts phone and date of birth while the User ID comes from the verified token.

**Try changing:** Give the Patient an existing `user_id` of `99` and model why the real handler returns `409` instead of overwriting it.

**Next:** Once a portal account resolves to a Patient, the application can safely load only that Patient's Call history and accept Feedback for owned Calls.

---
