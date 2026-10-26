# Agent instructions

These are the shared rules for every AI coding agent working in this repo.
The rules themselves live in two files, so read both before making a change:

- [CONTRIBUTING.md](CONTRIBUTING.md) covers the workflow from branch to merge, the conventions, and what stays out of the repo.
- [docs/architecture.md](docs/architecture.md) covers the stack, the environments, and the decisions log.

On top of those:

- Commits and pull requests carry only the author's name, so turn off any `Co-Authored-By` line, "Generated with" footer or session link your tool adds.
- Run the part's lint, type check and tests from the README before you push, because CI runs the same ones.
- Add your pull request's entry to `WORKLOG.md` under the author's section, as described in CONTRIBUTING.md.
- Add a line to the decisions log in `docs/architecture.md` when you make a choice the next person would ask about.
- Keep this file short, and put any new rule in CONTRIBUTING.md so people and agents follow the same one.
