## Requirement

The repository has no license file, and `pyproject.toml` says "Proprietary", so no one else may use, copy or change any of it. The product isn't worth selling: running and steering agents is a crowded field of free tools, and the buyers who pay need authentication, several users and hosting, all non-goals. Releasing it pays in reputation, feedback and adoption, and those need a license that lets people use it.

The app is licensed MIT, as most free tools of its kind are: short, permissive and widely understood. The repo template is licensed MIT-0. Its files are copied into other repositories, so any obligation they carried, even MIT's requirement to keep a notice, would follow them into every onboarded repository. MIT-0 asks for nothing.

## Acceptance Criteria

1. `LICENSE` at the repository's root holds the MIT License, and a wheel built with `uv build` declares `MIT` and carries the license files.
2. `templates/LICENSE` holds MIT-0 for `templates/default-repo/`. Setup and template sync never copy it into a repository.
3. Both license files name Edward Liveikis as the copyright holder.
4. The vendored-library table, `static/vendor/README.md` in the package, gives each file's license: htmx.org is `0BSD`.
5. The README's License section says the app is MIT and the repo template MIT-0, and that Claude Code, which the Claude Agent SDK installs alongside, is Anthropic's, under Anthropic's own terms.
6. `specs/product.md` › Monetization says none is planned, and names the two licenses.

## Out of scope

- Making the repository public, publishing to PyPI, or building executables. A bundled executable would include the `claude` binary that the Claude Agent SDK ships, which is Anthropic's under its own terms, so it needs its own check first.
- Removing personal or host-specific content from the git history before going public.
- Changing the default Claude login for a released version. Anthropic doesn't allow third-party products to offer claude.ai login without its approval.
- License headers in each file.
- A trademark policy for the name.

## Implementation Notes

- `pyproject.toml` declares the license as an SPDX expression with its license files (PEP 639).
- `templates/README.md` says why the template's license sits outside `default-repo/`.
