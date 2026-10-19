# Lesson 3 — Gateway Route Rewriting

## 3. Gateway route rewriting

**Definition:** Gateway route rewriting removes the public service prefix and forwards the remaining path to the selected internal service.

For Domain requests, Nginx applies:

```shell
location /api/domain/ {
    rewrite ^/api/domain/(.*)$ /$1 break;
    proxy_pass $domain;
}
```

Therefore:

```shell
Public request:     GET /api/domain/slots?limit=2
Matched location:  /api/domain/
Rewritten request: GET /slots?limit=2
Internal target:   http://domain:8000
```

The query string remains attached. Only the path prefix is removed.

### Code example — Request two public Slots

**Predict first:** Predict the internal path Domain will log and the maximum number of JSON objects returned.

```bash
curl -i 'http://localhost/api/domain/slots?limit=2'
```

**Trace it:** The operating system connects to host port 80. Gateway matches `/api/domain/`, rewrites the path to `/slots`, and uses Docker DNS to reach `domain:8000`. Domain's `GET /slots` handler receives `limit=2`.

**What to notice:** The browser knows the public path, while FastAPI registers and receives the shorter internal path.

**Try changing:** Change `limit=2` to `limit=1` and predict the response-array length.

**Next:** A route explanation becomes trustworthy when HTTP output and logs confirm it at runtime.
