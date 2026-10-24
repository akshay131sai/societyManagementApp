# Marketing assets

Drop the two brand files here, then run `bash ../embed-assets.sh` from this
folder's parent (`apps/marketing`).

| File | What it is | Notes |
|---|---|---|
| `cover.jpg` | The wide NestFlow banner — buildings, garden, blue sky | `.jpeg`, `.png` and `.webp` also work. Keep it under ~600 KB; it is base64-embedded, which adds about 33% |
| `logo.png` | The NestFlow mark — house, family, towers, leaf, ribbon sphere | Transparent background, square, ideally 512×512 or larger |

`embed-assets.sh` inlines both as `data:` URIs inside `index.html`, because the
published Artifact runs under a CSP that blocks every external host. Inlining
also means `index.html` opens correctly straight off disk with no server.

Until the files are here, the page renders a hand-built stand-in: a CSS/SVG
apartment skyline in the hero, and a vector redraw of the logo in the six
places the mark appears (nav, footer, laptop sidebar, resident phone, the CTA
lockup, and the watermark behind the laptop).

Flags: `--cover-only` and `--logo-only` embed just one half.
