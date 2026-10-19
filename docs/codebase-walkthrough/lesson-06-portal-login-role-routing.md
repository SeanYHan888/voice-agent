# Lesson 6 — Portal Login and Role Routing

## 6. Portal login and role routing

**Definition:** Portal login verifies an account's password, returns a signed JWT, and uses the returned role to select the Patient or Admin interface.

The flow is:

```shell
email + password
  -> React Login.submit()
  -> AuthProvider.login()
  -> POST /api/auth/login
  -> Gateway rewrites to POST /login
  -> LoginIn validation
  -> User lookup and bcrypt verification
  -> JWT with sub, email, role, iat, exp
  -> {access_token, token_type, role}
  -> localStorage: maya.token and maya.role
  -> patient: /portal | admin: /admin
```

The important JWT claims are:

| Claim | Meaning |
|---|---|
| `sub` | Auth service User ID |
| `email` | Portal email address |
| `role` | `patient` or `admin` |
| `iat` | Issued-at time |
| `exp` | Expiration time |

The browser stores `maya.role` for navigation convenience, but it is not the security boundary. A person can edit local storage. They cannot change a signed JWT payload without invalidating its signature, and protected backend endpoints check the token again.

Main failure paths:

- Malformed email: `422` during request-model validation.
- Unknown email or wrong password: `401` from the login handler.
- Expired or invalid JWT on a later request: `401`; the API client clears browser session storage and returns to `/login`.

### Code example — Predict role routing

**Predict first:** Predict the two printed paths.

```python
def home_for(role: str) -> str:
    return "/admin" if role == "admin" else "/portal"

print(home_for("patient"))
print(home_for("admin"))

assert home_for("patient") == "/portal"
assert home_for("admin") == "/admin"
```

**Trace it:** The function mirrors the decision in `Login.tsx`. The returned role is compared with `admin`; an Admin goes to `/admin`, and every other expected portal role goes to `/portal`.

**What to notice:** Role routing decides which interface to show. Authorization is a separate server-side decision made when protected data is requested.

**Try changing:** Pass `"owner"` and explain why this frontend default would be unsafe if the backend trusted it.

**Next:** Login proves which portal account is present; account-to-Patient linking determines which clinic Patient record that account may access.
