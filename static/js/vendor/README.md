# Vendored third-party assets

Checked in rather than pulled from a CDN at runtime: a self-hosted Jackil
has to work with no route to the internet.

## gridstack.js

| | |
|---|---|
| Version | 12.4.0 |
| Licence | MIT (`gridstack.LICENSE`) |
| Upstream | https://github.com/gridstack/gridstack.js |
| `gridstack-all.js` | sha256 `6e3032a6906805e43ca7e2dc818989b170bb65b686a6d0e89e6b68ad61f5946f` |
| `../css/vendor/gridstack.min.css` | sha256 `55e9d4ea6d8c6f8f1ea8a449b8af18d8571487c0afc6b433cccf877047cb8457` |

The same files Vigil ships. Drives the dashboard grid.

## KaTeX

| | |
|---|---|
| Version | 0.19.0 (released 2026-10-01) |
| Licence | MIT (`katex/LICENSE`) |
| Upstream | https://github.com/KaTeX/KaTeX |
| `katex/katex.min.js` | sha256 `103a53763cc033bba8d175bf3f0ba597c3505c9b6747dd3f2c7bc2a6bfcc8ae7` |
| `../../css/vendor/katex/katex.min.css` | sha256 `d4ab5b8ee16989b070cdb0ea24bd6ad48fc8df1b787f280f29d3ae4f959f2c00` |
| `katex/contrib/auto-render.min.js` | sha256 `e5372d199bcdae8b4de71d0f7ceba72a4ba12774a27c60a6f1f77d03b3228ee4` |

Math is rendered client-side by `../jackil-math.js` from the
`span.math.inline` / `div.math.block` the server renderer emits. The CSS
loads its `fonts/` relative to itself, so `../../css/vendor/katex/fonts`
stays beside it.
