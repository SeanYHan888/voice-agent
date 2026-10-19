# Lesson 5 — Failure Ownership

## 5. Failure ownership

**Definition:** Failure ownership identifies the first layer that rejects a request, rather than blaming the last component visible to the caller.

Two harmless failures demonstrate different FastAPI mechanisms:

| Request | Status | Owner | Reason |
|---|---:|---|---|
| `/api/domain/does-not-exist` | `404` | Domain's FastAPI router | No internal `/does-not-exist` route exists |
| `/api/domain/slots?limit=201` | `422` | FastAPI/Pydantic validation | `limit` is constrained to at most 200 |

Both requests reach Domain successfully. For the `422`, validation occurs before the `slots()` function body, so PostgreSQL is not queried.

### Code example — Compare `404` and `422`

**Predict first:** Predict which response says `Not Found` and which mentions `less_than_equal`.

```bash
curl -sS -i 'http://localhost/api/domain/does-not-exist'
curl -sS -i 'http://localhost/api/domain/slots?limit=201'
```

**Trace it:** Gateway rewrites and forwards both requests. Domain routing fails to match the first and returns `404`. Domain routing matches the second, but query-parameter validation rejects `201` before executing the handler.

**What to notice:** A status code describes the failure category; logs and the response body locate the mechanism that produced it.

**Try changing:** Use `limit=hello` and explain why it is still a `422` but violates a different part of the input contract.

### Integration example — Follow one value across Gateway and Domain

**Predict first:** For `limit=3`, predict the public path, internal path, validation result, and maximum output length.

```bash
curl -sS 'http://localhost/api/domain/slots?limit=3' \
  | python3 -c 'import json,sys; rows=json.load(sys.stdin); print(len(rows)); assert len(rows) <= 3'
```

**Trace it:** The value `3` begins in the public query string, survives Gateway rewriting, becomes the integer `limit` in FastAPI, controls SQL's `LIMIT`, and finally bounds the JSON array length.

**What to notice:** One value can cross transport, validation, query construction, and response serialization without changing its meaning.

**Try changing:** Use `limit=0`; observe the result and decide whether zero should remain a valid product behavior.

**Next:** With ordinary routing understood, trace how the application establishes a portal identity.

---
