# AGENTS.md — agent routing index

Agents: explore the repo directly; this file is a routing index, not a contributor guide.

## Workflow

**Session memory:** Write plans, notes, and ephemeral files to `.tmp/`
(gitignored) rather than the system temporary directory.

**For non-trivial planning**, inspect deps and tooling:
`pyproject.toml` · `tox.ini` · `.pre-commit-config.yaml` ·
`requirements.txt` · `test-requirements.txt`

**Tests:** Use `tox` or `stestr`; never use `pytest`.
Invoke them directly, for example `tox -e pep8`.
Assume project tools are installed and available on `$PATH`.

**Routing:**
- Repo layout: [repo-overview.rst](doc/source/contributor/repo-overview.rst)
- Contributor entry point: [CONTRIBUTING.rst](CONTRIBUTING.rst)
- Cinder contributor guide: [contributing.rst](doc/source/contributor/contributing.rst)
- Style, hacking, checks: [HACKING.rst](HACKING.rst)
- Development environment: [development.environment.rst](doc/source/contributor/development.environment.rst)
- Testing: [testing.rst](doc/source/contributor/testing.rst)
- Documentation: [documentation.rst](doc/source/contributor/documentation.rst)
- Dependencies and packaging: [dependencies.rst](doc/source/contributor/dependencies.rst)
- Commit messages: [commit-messages.rst](doc/source/contributor/commit-messages.rst)
- Gerrit/reviews/vendor CI: [gerrit.rst](doc/source/contributor/gerrit.rst)
- Architecture: [architecture.rst](doc/source/contributor/architecture.rst)
- REST API/microversions: [api_microversion_dev.rst](doc/source/contributor/api_microversion_dev.rst) / [api_microversion_history.rst](doc/source/contributor/api_microversion_history.rst)
- RPC: [rpc.rst](doc/source/contributor/rpc.rst)
- Threading/concurrency: [threading.rst](doc/source/contributor/threading.rst)
- Attach/detach flows: [attach_detach_conventions.rst](doc/source/contributor/attach_detach_conventions.rst) / [attach_detach_conventions_v2.rst](doc/source/contributor/attach_detach_conventions_v2.rst)
- Conditional DB updates: [api_conditional_updates.rst](doc/source/contributor/api_conditional_updates.rst)
- Drivers: [drivers.rst](doc/source/contributor/drivers.rst) / [new_driver_checklist.rst](doc/source/contributor/new_driver_checklist.rst) / [drivers_locking_examples.rst](doc/source/contributor/drivers_locking_examples.rst)
- Rolling upgrades and DB migrations: [rolling.upgrades.rst](doc/source/contributor/rolling.upgrades.rst) / [database-migrations.rst](doc/source/contributor/database-migrations.rst)
- Release notes: [releasenotes.rst](doc/source/contributor/releasenotes.rst)
- Agentic coding conventions: [agentic-coding.rst](doc/source/contributor/agentic-coding.rst)

## Guardrails

- **Tools:** Do not install missing tools with a package manager or `pip`.
- **Concurrency:** Review the threading docs before changing concurrent code.
- **Review:** Cinder uses Gerrit, not GitHub PRs. Series are always unsquashed;
  each commit must be independently testable and correct.
- **Git:** Read-only operations (`git log`, `git diff`, `git status`) are fine.
  Do not run mutating operations (`add`, `commit`, `reset`, `checkout`, `push`,
  `stash`, `merge`, `rebase`, etc.) unless explicitly instructed.
