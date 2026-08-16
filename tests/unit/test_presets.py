# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for cutting data presets (loobric_server/presets.py): the
normal form, the floor, the ratified op_type vocabulary, and listing
filters. A preset is a recommendation with a source, never a fact."""
import pytest

from loobric_server.contract.models import OP_TYPES, PresetEntry
from loobric_server.presets import (PresetError, filter_entries,
                                    normalize_contribution)


def _payload(**overrides):
    payload = {"origin": "manufacturer", "label": "6061 profiling",
               "material": {"name": "6061-T6"},
               "op_type": "profiling",
               "vc": {"value": 250, "unit": "m/min"},
               "fz": {"value": 0.05, "unit": "mm"}}
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not None}


class TestNormalize:
    def test_happy_path(self):
        n = normalize_contribution(_payload())
        assert n["origin"] == "manufacturer"
        assert n["label"] == "6061 profiling"
        assert n["data"]["material"] == {"name": "6061-T6"}
        assert n["data"]["vc"] == {"value": 250, "unit": "m/min"}

    def test_origin_and_label_required(self):
        with pytest.raises(PresetError, match="origin"):
            normalize_contribution(_payload(origin=" "))
        with pytest.raises(PresetError, match="label"):
            normalize_contribution(_payload(label=""))

    def test_material_required_verbatim(self):
        with pytest.raises(PresetError, match="material"):
            normalize_contribution(_payload(material=None))
        n = normalize_contribution(
            _payload(material={"name": "Al 6061", "uuid": "abc-123"}))
        assert n["data"]["material"] == {"name": "Al 6061", "uuid": "abc-123"}

    def test_floor_needs_one_engineering_value(self):
        with pytest.raises(PresetError, match="engineering value"):
            normalize_contribution(_payload(vc=None, fz=None))

    def test_single_value_meets_floor(self):
        n = normalize_contribution(_payload(fz=None))
        assert n["data"]["vc"]["value"] == 250
        assert n["data"]["fz"] is None

    def test_op_type_vocabulary_is_ratified(self):
        with pytest.raises(PresetError, match="ratified"):
            normalize_contribution(_payload(op_type="milling"))

    def test_op_type_optional(self):
        assert normalize_contribution(_payload(op_type=None))["op_type"] is None

    def test_values_must_be_positive_numbers(self):
        with pytest.raises(PresetError, match="vc"):
            normalize_contribution(_payload(vc={"value": -3}))
        with pytest.raises(PresetError, match="fz"):
            normalize_contribution(_payload(fz={"value": "fast"}))

    def test_unknown_top_level_keys_rejected(self):
        with pytest.raises(PresetError, match="unknown keys"):
            normalize_contribution(_payload(rpm=10000))

    def test_extras_bag_passes_verbatim(self):
        n = normalize_contribution(
            _payload(extras={"coolant": "flood", "DOC": "0.5xD"}))
        assert n["data"]["extras"] == {"coolant": "flood", "DOC": "0.5xD"}

    def test_raw_feed_rpm_never_normal_form(self):
        # The G5 rule at the door: feed/rpm are not fields; they land in
        # `unknown keys`, and the message points at conversion.
        with pytest.raises(PresetError):
            normalize_contribution(_payload(feed_rate=800))


class TestContractShape:
    def test_entry_model_floor(self):
        with pytest.raises(Exception):
            PresetEntry.model_validate(
                {"id": "x", "origin": "user", "label": "l",
                 "material": {"name": "steel"}})

    def test_entry_model_op_type_enum(self):
        with pytest.raises(Exception):
            PresetEntry.model_validate(
                {"id": "x", "origin": "user", "label": "l",
                 "material": {"name": "steel"}, "op_type": "wat",
                 "vc": {"value": 100}})

    def test_op_types_seeded(self):
        assert "profiling" in OP_TYPES and "engraving" in OP_TYPES


class TestFilters:
    def _entries(self):
        return [
            {"origin": "freecad", "label": "a",
             "material": {"name": "6061-T6"}, "op_type": "profiling"},
            {"origin": "manufacturer", "label": "b",
             "material": {"name": "6061-t6"}, "op_type": "slotting",
             "machine_id": "m1"},
        ]

    def test_material_match_is_case_insensitive_verbatim(self):
        assert len(filter_entries(self._entries(), material="6061-T6")) == 2

    def test_origin_filter(self):
        out = filter_entries(self._entries(), origin="Manufacturer")
        assert [e["label"] for e in out] == ["b"]

    def test_op_type_and_machine_filters(self):
        assert filter_entries(self._entries(), op_type="slotting",
                              machine_id="m1")[0]["label"] == "b"
