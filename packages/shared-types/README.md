# packages/shared-types

Reserved for types shared between the web and mobile clients once both exist.

Nothing lives here yet, deliberately: extracting a shared package with exactly
one consumer adds a build step and buys nothing. The web client owns its types
in `apps/web/src/types` until the mobile client needs the same shapes.
