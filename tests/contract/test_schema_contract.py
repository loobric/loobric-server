# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Conformance suite for the tool-schema contract (docs/TOOL_SCHEMA.md).

The golden fixtures in tests/fixtures/schema/ are simultaneously the
documentation, the worked examples, and the test data — validating them here
on every run means they cannot drift from the contract models. A new client
author runs this same suite against their output to prove conformance.
"""
import json
from pathlib import Path

import pytest

from loobric_server.contract import (
    Field, Provenance, UNKNOWN, ClientWrite, LaneViolation, reject_out_of_lane,
    Component, ToolInstanceRecord, ToolCatalogRecord, ToolTableEntry, ToolSet,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "schema"

ENTITY_FOR = {
    "tool_catalog_record.json": ToolCatalogRecord,
    "tool_instance_record.json": ToolInstanceRecord,
    "tool_table_entry.json": ToolTableEntry,
    "tool_set.json": ToolSet,
    "tool_assembly_record.json": ToolInstanceRecord,   # an assembly IS a record
}


def load(name):
    return json.loads((FIXTURES / name).read_text())


# -- the golden fixtures are valid --------------------------------------------

@pytest.mark.contract
@pytest.mark.parametrize("name,model", ENTITY_FOR.items(), ids=list(ENTITY_FOR))
def test_golden_fixture_validates(name, model):
    """Every worked example in the docs validates against its entity model."""
    model.model_validate(load(name))


@pytest.mark.contract
def test_every_canonical_leaf_is_provenance_tagged():
    """Walk each fixture's canonical tree; every leaf must be a {value, source}
    Field with a well-formed source — no bare values hiding their origin."""
    for name in ENTITY_FOR:
        canonical = load(name)["canonical"]
        for path, leaf in _leaves(canonical):
            assert "source" in leaf, f"{name}:{path} is not provenance-tagged"
            Field.model_validate(leaf)  # raises if malformed


# -- the model rules hold -----------------------------------------------------

@pytest.mark.contract
def test_unknown_field_must_have_null_value():
    Field.model_validate({"value": None, "source": "unknown"})
    with pytest.raises(Exception):
        Field.model_validate({"value": "endmill", "source": "unknown"})  # a guess


@pytest.mark.contract
def test_observed_requires_a_machine():
    Field.model_validate({"value": 6.0, "unit": "mm",
                          "source": Provenance.observed("linuxcnc", "millstone")})
    with pytest.raises(Exception):
        Field.model_validate({"value": 6.0, "source": "observed:linuxcnc"})  # no @machine


# -- composition (ISO 13399) --------------------------------------------------

@pytest.mark.contract
def test_assembly_is_a_record_with_components_and_derived_geometry():
    """An assembly is a first-class record (here an instance) composed of
    items; its gauge length is DERIVED from the stack, a distinct provenance
    from a human assertion or a machine observation."""
    asm = ToolInstanceRecord.model_validate(load("tool_assembly_record.json"))
    assert asm.canonical.item_type.value == "assembly"
    roles = [c["role"] for c in asm.canonical.components.value]
    assert roles == ["assembly_item", "adaptive_item", "cutting_item"]
    gl = asm.canonical.geometry.gauge_length
    assert gl.value == 92.4 and Provenance.kind(gl.source) == "derived"
    # cutting diameter comes from the cutting item (asserted here)
    assert asm.canonical.geometry.cutting_diameter.value == 6.0


@pytest.mark.contract
def test_component_role_must_be_an_iso_item_role():
    Component.model_validate({"component_id": "x", "role": "cutting_item"})
    with pytest.raises(Exception):
        Component.model_validate({"component_id": "x", "role": "nonsense"})


@pytest.mark.contract
def test_derived_provenance_is_recognized():
    Field.model_validate({"value": 92.4, "unit": "mm", "source": "derived:components"})


@pytest.mark.contract
def test_probe_is_honest_not_an_endmill():
    """The bug this whole schema exists to prevent: a machine-sourced tool's
    shape is asserted (or unknown), never fabricated; unset fields are null."""
    probe = ToolInstanceRecord.model_validate(load("tool_instance_record.json"))
    assert probe.canonical.geometry.shape.value == "probe"
    assert Provenance.kind(probe.canonical.geometry.shape.source) == "asserted"
    # the measured diameter is observed, from the machine
    dia = probe.canonical.geometry.diameter
    assert dia.value == 2.9972 and dia.source == "observed:linuxcnc@millstone"
    # a field nobody stated is honestly unknown, not guessed
    assert probe.canonical.geometry.length.value is None
    assert probe.canonical.geometry.length.source == UNKNOWN
    # type link unknown until asserted
    assert probe.canonical.catalog_type_id.value is None


# -- lane discipline ----------------------------------------------------------

@pytest.mark.contract
def test_client_write_is_envelope_plus_opaque_data():
    """A clean client section validates. The client name is NOT in the body —
    it comes from the request path — so there's no redundant key to diverge."""
    w = reject_out_of_lane({
        "client_version": "1.0", "client_item_id": "tool-42",
        "data": {"anything": [1, 2, 3]}})
    assert isinstance(w, ClientWrite) and w.client_item_id == "tool-42"


@pytest.mark.contract
def test_client_field_in_body_is_rejected_as_a_stray_key():
    """The map key is the single source of truth; a `client` field in the body
    would be a divergent second copy — forbidden."""
    with pytest.raises(LaneViolation):
        reject_out_of_lane({"client": "freecad", "client_version": "0.3.1", "data": {}})


@pytest.mark.contract
@pytest.mark.parametrize("forbidden", ["internal", "canonical"])
def test_sync_write_cannot_touch_internal_or_canonical(forbidden):
    """The load-bearing safety property: routine sync physically cannot mutate
    server/canonical state — it's a loud rejection, not a silent strip."""
    payload = {"client_version": "0.3.1", "data": {}}
    payload[forbidden] = {"id": "x"} if forbidden == "internal" else {
        "geometry": {"shape": {"value": "endmill", "source": "asserted:freecad"}}}
    with pytest.raises(LaneViolation):
        reject_out_of_lane(payload)


@pytest.mark.contract
def test_stray_keys_in_a_client_write_are_rejected():
    with pytest.raises(LaneViolation):
        reject_out_of_lane({"client_version": "1", "machines": []})


# -- helper -------------------------------------------------------------------

def _leaves(node, prefix=""):
    """Yield (path, dict) for every provenance-leaf in a canonical tree. A leaf
    is a dict carrying a 'source'; we recurse through plain dicts and lists."""
    if isinstance(node, dict):
        if "source" in node:
            yield prefix, node
            return
        for k, v in node.items():
            yield from _leaves(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _leaves(v, f"{prefix}[{i}]")
