# Vendored front-end libraries

Served from here, so pages never load code from a CDN at runtime (ADR-005). Each file is an unmodified copy of a published release. To upgrade, replace the file from the package's npm tarball and update its row, its license included.

| File | Package and version | License | Source | SHA-256 |
|------|---------------------|---------|--------|---------|
| `htmx.min.js` | htmx.org 2.0.11 | `0BSD` | `dist/htmx.min.js` in https://registry.npmjs.org/htmx.org/-/htmx.org-2.0.11.tgz | `d6fdc75f204e6bdefa99b69bf1e6d4ac69b8a364f77929f45c13476b4000f717` |
