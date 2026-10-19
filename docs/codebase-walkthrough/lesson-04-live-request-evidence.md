# Lesson 4 — Live Request Evidence

## 4. Live request evidence

**Definition:** Live request evidence is the combination of an HTTP response and service logs that proves which components processed one request.

A live request returned `200 OK`, two open future Slots, and a response header like:

```shell
x-request-id: ca3e608fb9220525c83c05eaacad599a
```

The corresponding logs showed:

```shell
gateway: GET /api/domain/slots?limit=2 -> 200
domain:  GET /slots -> 200 ... rid=ca3e608fb9220525c83c05eaacad599a
```

The matching request ID connects the public request to the internal service event. The differing paths prove that Gateway stripped `/api/domain`.

The Domain handler then:

1. Selects `Slot` rows.
2. Joins `VisitType`.
3. Keeps only `status == "open"` and future start times.
4. Orders by start time.
5. Applies the caller's `limit`.
6. Converts rows to `SlotOut` response objects.

### Code example — Match one request to recent logs

**Predict first:** Predict which two containers will log the request. Auth, Agent, and Frontend should remain outside this path.

```bash
curl -sS -D - 'http://localhost/api/domain/slots?limit=2'
docker compose logs --since=30s --tail=50 gateway domain
```

**Trace it:** The first command exposes the status, body, and `x-request-id`. The second limits evidence to Gateway and Domain over a short time window. Match the request path, status, timestamp, and request ID.

**What to notice:** A `Server: nginx` response header only proves the response passed through Nginx; correlated logs identify which upstream produced its status.

**Try changing:** Request `providers` instead of `slots` and identify which portions of the path stay the same.

**Next:** The same evidence method can distinguish routing failures from input-validation failures.
