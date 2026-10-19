# Module 2 — Portal Authentication

### Visual model — Credentials become an authenticated browser session

```mermaid
sequenceDiagram
    participant B as Browser
    participant G as Gateway
    participant A as Auth service
    participant P as PostgreSQL
    B->>G: POST /api/auth/login
    G->>A: POST /login
    A->>P: Find User by email
    P-->>A: User and password hash
    A->>A: bcrypt check and JWT signing
    A-->>B: access_token and role
    B->>B: Store token and choose route
```

**How to read it:** Begin with the credentials in the Browser. Gateway changes only the route, Auth verifies the account and signs the identity claim, and the Browser stores the result. A successful login reads the database but does not modify it.
