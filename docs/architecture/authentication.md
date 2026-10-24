# Authentication & Authorization

## 1. The split

| Firebase owns | NestFlow owns |
|---|---|
| Identity (who you are) | Authorization (what you may do) |
| Credential storage, password hashing | Society membership |
| Login, signup, password reset | Roles and permissions |
| Identity providers (password, Google, phone OTP) | Flat assignment |
| Email verification | Account status within the society |
| The `firebase_uid` | Subscription entitlement |
| ID token issuance and signing | Every access decision |

**Firebase custom claims are never consulted for authorization.** They are
client-writable-adjacent (settable by anyone with the Admin SDK), cached in the
token for up to an hour, and cannot be revoked promptly. Authorization is
resolved from PostgreSQL on every request so that a role change, a lock, or a
subscription expiry takes effect on the *next request*, not the next hour.

The only thing NestFlow takes from the verified token is the `firebase_uid`
(and `email` / `email_verified` for first-time linking).

## 2. Flow

```
  User                React               Firebase Auth            FastAPI
   |                    |                       |                     |
   |-- credentials ---->|                       |                     |
   |                    |-- signIn ------------>|                     |
   |                    |<-- ID token (JWT) ----|                     |
   |                    |                       |                     |
   |                    |-- GET /auth/me ------------------------------>|
   |                    |   Authorization: Bearer <id-token>          |
   |                    |                       |                     |
   |                    |                       |<-- verify_id_token -|
   |                    |                       |--- uid, email ----->|
   |                    |                                             |
   |                    |                    [ central DB lookup ]    |
   |                    |                    platform_users           |
   |                    |                    societies                |
   |                    |                    subscriptions            |
   |                    |                                             |
   |                    |                    [ tenant DB lookup ]     |
   |                    |                    users, roles, perms      |
   |                    |                    theme_settings           |
   |                    |                                             |
   |                    |<-- Principal + theme + nav ------------------|
```

The client stores **no** NestFlow session. The Firebase SDK holds the refresh
token and mints a fresh ID token; the API client attaches
`Authorization: Bearer <token>` to every request and retries once on a 401 after
forcing a token refresh.

## 3. Token verification

`app/core/firebase.py` wraps the Admin SDK:

```python
decoded = firebase_admin.auth.verify_id_token(
    token,
    check_revoked=True,     # honours Firebase-side session revocation
)
```

This validates signature (against Google's rotating public keys, cached by the
SDK), `iss`, `aud` (must equal our project id), `exp`, `iat` and `sub`.

Failure modes map to explicit error codes:

| Firebase exception | HTTP | code |
|---|---|---|
| `ExpiredIdTokenError` | 401 | `TOKEN_EXPIRED` |
| `RevokedIdTokenError` | 401 | `TOKEN_REVOKED` |
| `InvalidIdTokenError`, `CertificateFetchError` | 401 | `TOKEN_INVALID` |
| valid token, no `platform_users` row | 401 | `USER_NOT_REGISTERED` |
| `platform_users.is_active = false` | 403 | `USER_DISABLED` |

`USER_NOT_REGISTERED` is deliberate and important: authenticating with Firebase
does **not** create a NestFlow account. Users are provisioned by a Super Admin
(society admins) or a Society Admin (residents, staff). Self-signup into a
society is not a thing.

## 4. The Principal

The single object every guard and service reads:

```python
@dataclass(frozen=True, slots=True)
class Principal:
    platform_user_id: UUID
    firebase_uid: str
    email: str
    display_name: str
    is_super_admin: bool
    society_id: UUID | None          # None only for SUPER_ADMIN
    tenant_user_id: UUID | None      # id inside the tenant DB
    roles: frozenset[Role]
    permissions: frozenset[Permission]
    flat_ids: frozenset[UUID]        # for FLAT_OWNER scoping

    def has(self, p: Permission) -> bool: ...
    def owns_flat(self, flat_id: UUID) -> bool: ...
```

It is immutable and built once per request. Services receive it explicitly —
there is no ambient/threadlocal "current user".

### Resolution cost

Building a Principal costs two central-DB queries and one tenant-DB query.
This runs per request for correctness. The measured cost is ~3ms on a warm
pool. A short-TTL (10s) in-process cache keyed by `firebase_uid`, with an
explicit invalidation hook on role and lock changes, remains available as an
optimisation — deliberately not enabled, because a stale authorization cache is
exactly the bug class we avoided by not using custom claims.

The same resolution runs on the `/ws` handshake, so a WebSocket is not a way
around any of it: a locked society or an expired subscription is refused at
connect, and a token that expires ends the connection at its next reconnect.

## 5. Dependency composition

```python
# app/api/deps.py

get_bearer_token          -> str
get_firebase_identity     -> FirebaseIdentity        (uid, email, email_verified)
get_principal             -> Principal               (central + tenant resolution)
require_super_admin       -> Principal
require_active_society    -> Principal               (status guard)
require_active_subscription -> Principal             (entitlement guard)
get_tenant_session        -> AsyncSession            (after both guards)
require_permission(P)     -> Callable[..., Principal]
```

Typical tenant route:

```python
@router.get("/flats")
async def list_flats(
    page: PageParams = Depends(),
    principal: Principal = Depends(require_permission(Permission.FLAT_READ)),
    db: AsyncSession = Depends(get_tenant_session),
) -> Envelope[Page[FlatRead]]:
    return ok(await flat_service.list(db, principal, page))
```

Typical platform route:

```python
@router.post("/societies", status_code=201)
async def create_society(
    body: SocietyCreate,
    principal: Principal = Depends(require_super_admin),
    db: AsyncSession = Depends(get_central_session),
) -> Envelope[SocietyRead]: ...
```

## 6. Dev auth provider (development only)

No Firebase project is configured yet, so `app/core/firebase.py` selects a
verifier by configuration:

```
AUTH_PROVIDER=firebase   -> FirebaseTokenVerifier   (production)
AUTH_PROVIDER=dev        -> DevTokenVerifier        (local only)
```

`DevTokenVerifier` accepts `dev:<email>` as a bearer token and returns a
synthetic identity. It exists so Phase 1 is fully runnable and testable before
Firebase credentials exist.

Three independent safeties, so this cannot reach production:

1. `Settings` validation **raises at import time** if
   `ENVIRONMENT == "production" and AUTH_PROVIDER == "dev"`. The process will
   not boot.
2. The application startup hook logs a loud `SECURITY` warning banner whenever
   the dev provider is active.
3. `/api/v1/auth/me` returns `"auth_provider": "dev"` so the frontend can render
   a persistent development badge.

Switching to real Firebase is a `.env` change plus service-account credentials.
No application code changes.

## 7. Audit

Written to `platform_audit_logs` (central) or `audit_logs` (tenant) as
appropriate:

`LOGIN_SUCCESS`, `LOGIN_FAILED`, `TOKEN_REJECTED`, `USER_NOT_REGISTERED`,
`PERMISSION_DENIED`, `SOCIETY_CREATED`, `SOCIETY_LOCKED`, `SOCIETY_UNLOCKED`,
`SUBSCRIPTION_CHANGED`, `USER_CREATED`, `USER_DISABLED`, `ROLE_CHANGED`,
`TEMPLATE_VERSION_CREATED`, `BILLING_RUN_STARTED`, `BILLS_PUBLISHED`,
`PAYMENT_RECORDED`.

Each entry carries `request_id`, actor, target, IP, user agent and a JSON diff.

**Never logged:** ID tokens, refresh tokens, passwords, service-account keys,
payment credentials. `app/core/logging.py` installs a redaction filter that
scrubs `authorization`, `token`, `password`, `secret`, `private_key` keys from
structured log payloads regardless of call site.
