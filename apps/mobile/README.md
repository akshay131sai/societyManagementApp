# apps/mobile — future React Native client

Not built yet. This directory exists so the architecture stays honest about
where the mobile client will live.

## When it is built

```
React Native + Expo
Firebase Auth  (same project as the web client)
FastAPI        (the same /api/v1 endpoints — no mobile-specific API)
Firebase Cloud Messaging for push
```

## What is already in place for it

The backend was built API-first, so the mobile client needs no server changes:

| Requirement | Status |
|---|---|
| Client-agnostic REST API under `/api/v1` | Done — there is no `/api/web/*` |
| Token auth via `Authorization: Bearer` | Done — no cookies, no CSRF surface |
| Server-driven navigation | Done — `/auth/me` returns the nav tree, so a shipped mobile build picks up new modules without a release |
| Single bootstrap call | Done — `/auth/me` returns principal, society, subscription, theme and navigation together |
| Consistent response envelope | Done — one parser, one error path |
| Server-side pagination everywhere | Done — no endpoint returns an unbounded list |
| Per-society theming as data | Done — the same tokens drive a React Native StyleSheet |
| Push notification channel | Modelled — `notifications.channel` already has a `PUSH` value |

## What will need writing

- Native shell, navigation and screens
- `services/api.ts` equivalent (the web one is deliberately dependency-free and
  ports almost verbatim)
- FCM device-token registration endpoint
- Offline cache for bills and notices
