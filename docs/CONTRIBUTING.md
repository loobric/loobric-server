# Contributing to Loobric Server

## Development Documentation

Before contributing, please review these key documents:

- **[DEVELOPMENT.md](DEVELOPMENT.md)** — environment setup, running tests, repo layout.
- **[DESIGN_PHILOSOPHY.md](DESIGN_PHILOSOPHY.md)** — the principles every change is held to.
- **[ARCHITECTURE.md](ARCHITECTURE.md)** — how the system fits together.
- **[TOOL_SCHEMA.md](TOOL_SCHEMA.md)** — the authoritative contract for the public API.
- **[UBIQUITOUS_LANGUAGE.md](UBIQUITOUS_LANGUAGE.md)** — the project vocabulary. **Read the
  language gate:** no new user-facing word (endpoint path, response field, CLI verb, UI label)
  ships without an entry here. A concept on the public surface that isn't in the glossary is a
  bug, not a feature.

## Licensing & the CLA

Loobric Server is licensed **AGPL-3.0**. Contributing to **loobric-server** requires signing the
project **CLA** (see [CLA.md](CLA.md)) on your first pull request — it grants the maintainer
the rights needed to offer the commercial/hosted edition alongside the open core. The reference
**clients** (`loobric-freecad`, `loobric-linuxcnc`) are MIT and use **DCO sign-off** (`git commit
-s`) instead of a CLA.


## Development Process

Development follows the general concept outlined in the ZeroMQ Creative Code Construction Contract (C4).

### 1. Create an issue.
All issues in the tracker describe a 'problem'
- A 'problem' is something the user wants to achieve and cannot given the current design.
- Problems may including performance problems, security vulnerabilities, and other less tangible things but are all problems.
- Framing issues this way causes the dicussion to focus on solvable problems, demonstrable need and makes a proposed solution easier to validate.

**Good Examples:**
- "User can't attach a STEP file to a tool item"
- "Searching for tool items is slow"
- "Deleting a tool set causes a crash"

**Bad Examples:**
- "Add STEP import feature"
- "Make searching fast.
- "Add security vulnerability fix"

### 2. Allow time for discussion
- Allow time for discussion and disagreement
- Don't rush to implement a solution.  Good ideas take time to develop and alternate solutions may be superior.

### 3. Follow TDD
1. Write tests first
2. Implement minimal code to pass tests
3. Refactor as needed

### 4. Code Style
- Functional programming style
- Type hints for all functions
- Google-style docstrings
- 100 char line length
- Keep modules and functions small and focused

### 5. Commit Messages
- Use imperative verb
- Keep it short
- Reference an open issue

### 6. Rebase your branch
- Rebase your branch on top of main 
- Squash unnecessary commits.
- To allow bisecting, every commit should run and pass tests.  If it doesn't, squash it out.

### 7. Open a Pull Request
- Reference related issues
- Keep changes focused
- Ensure all tests pass

### 8. Don't be a jerk
- Be respectful to others

