# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""The gate: the published surface speaks ONLY the facade vocabulary.

`UBIQUITOUS_LANGUAGE.md` ("Language rule — the gate") and `REBOOT.md` (R2) promise
three things this file enforces in CI so drift cannot recur:

1. The legacy deep-schema routers are LIVE but UNPUBLISHED — they must never
   appear in the published OpenAPI paths. (The glossary long *claimed* this was a
   tested contract; until the 2026-06-18 reboot it was not. Now it is.)
2. The concepts ripped out in the reboot — adopt / coverage / reconcile / mirror —
   never reappear on a public *path* or as a removed-*endpoint* call in a client.
3. The rejected *words* never reappear as user-facing TEXT in the bundled clients
   (button labels, help, toasts). This closes REBOOT R11 — the original gate only
   checked endpoint paths, so a web-UI "Adopt" button that correctly called
   `/bind` still shipped the dead word, and `--slot` reached the CLI the same way.
   The vocabulary scan below catches the word, not just the route.

If one of these fails, drift reached the surface. Fix the code, not this test.
"""
import pathlib
import re

import pytest

# Legacy deep-schema resources: still mounted (include_in_schema=False) for the
# v2 transition, but excluded from the published schema. See REBOOT.md R6.
LEGACY_DEEP_RESOURCES = {
    "tool-items", "tool-assemblies", "tool-instances", "tool-presets", "tool-usage",
}

# Retired concepts (glossary "Rejected / removed terms"). Matched as a path
# fragment, so they catch both `/.../adopt` endpoints and `/coverage` queries.
RETIRED_PATH_FRAGMENTS = ("/adopt", "/coverage", "/reconcile", "/mirror")

# Rejected user-facing WORDS (glossary "Rejected / removed terms"), matched as
# whole words anywhere in a bundled client — labels, help text, toasts, AND code,
# so the term can't survive as a comment either. Word-boundary + a stem so e.g.
# `adopt` catches `Adopt`/`adopted`, `slot` catches `slots`, `install` catches
# `installed`/`installs`. Use the canonical replacement instead:
#   adopt -> bind (a bind may mint) · install/installed -> bound/unbound
#   coverage -> (removed) · reconcile -> (removed; surfaced via Inbox)
#   needs attention -> Inbox · mirror -> link/linked · slot -> entry/ToolTableEntry
RETIRED_VOCABULARY = (
    r"\badopt[a-z]*",
    r"\binstall[a-z]*",
    r"\bcoverage\b",
    r"\breconcil[a-z]*",
    r"needs[ -]attention",
    r"\bmirror[a-z]*",
    r"\bslot[a-z]*",
)

# The facade resources that MUST be published (a positive control so the
# exclusion tests below can't pass vacuously by publishing nothing).
FACADE_RESOURCES = (
    "tool-instance-records", "tool-catalog-records", "tool-table-entry-records",
    "tool-set-records", "machine-records", "instance-inbox",
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _published_paths(solo_client):
    schema = solo_client.get("/api/v1/openapi.json").json()
    return list(schema.get("paths", {}).keys())


@pytest.mark.contract
def test_legacy_deep_routers_excluded_from_published_schema(solo_client):
    leaked = []
    for path in _published_paths(solo_client):
        parts = path.strip("/").split("/")          # ["api", "v1", "<resource>", ...]
        resource = parts[2] if len(parts) >= 3 else ""
        if resource in LEGACY_DEEP_RESOURCES:
            leaked.append(path)
    assert not leaked, "deep-schema routes leaked into the public OpenAPI: %s" % leaked


@pytest.mark.contract
def test_no_retired_concepts_on_public_paths(solo_client):
    offenders = []
    for path in _published_paths(solo_client):
        low = path.lower()
        for frag in RETIRED_PATH_FRAGMENTS:
            if frag in low:
                offenders.append((path, frag))
    assert not offenders, "retired concept on a public path: %s" % offenders


@pytest.mark.contract
def test_facade_resources_are_published(solo_client):
    paths = " ".join(_published_paths(solo_client))
    missing = [r for r in FACADE_RESOURCES if "/api/v1/%s" % r not in paths]
    assert not missing, "facade resource missing from the published schema: %s" % missing


BUNDLED_CLIENTS = ("loobric_server/web/static/index.html",)


@pytest.mark.contract
def test_bundled_clients_do_not_call_retired_endpoints():
    """The web UI and CLI shipped in this repo must not reference removed endpoints."""
    bad = []
    for rel in BUNDLED_CLIENTS:
        text = (REPO_ROOT / rel).read_text()
        for frag in RETIRED_PATH_FRAGMENTS:
            if frag in text:
                bad.append("%s references %s" % (rel, frag))
    assert not bad, bad


@pytest.mark.contract
def test_bundled_clients_do_not_use_retired_vocabulary():
    """REBOOT R11: the rejected WORDS must not appear as user-facing text (or
    anywhere) in the bundled web UI / CLI. The endpoint test above passes when a
    client calls the *right* route but still shows the *wrong* word — this is the
    scan that would have caught the web-UI 'Adopt' button and the `--slot` flag.
    Fix the wording (see the glossary's replacement column), not this test."""
    patterns = [(p, re.compile(p, re.IGNORECASE)) for p in RETIRED_VOCABULARY]
    offenders = []
    for rel in BUNDLED_CLIENTS:
        for n, line in enumerate((REPO_ROOT / rel).read_text().splitlines(), 1):
            for term, rx in patterns:
                if rx.search(line):
                    offenders.append("%s:%d uses %s -> %r" % (rel, n, term, line.strip()[:80]))
    assert not offenders, "rejected vocabulary in a bundled client:\n" + "\n".join(offenders)
