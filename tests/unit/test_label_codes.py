# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for short label codes (loobric_server/label_codes.py)."""
import pytest

from loobric_server import label_codes
from loobric_server.label_codes import (
    ALPHABET, CODE_LENGTH, generate_code, new_unique_code, normalize_code,
)


class TestAlphabet:
    def test_excludes_ambiguous_letters(self):
        """Crockford base32: no I, L, O, U — a printed code can't be
        misread as 0/O or 1/I/l, and can't spell rude English words."""
        for letter in "ILOU":
            assert letter not in ALPHABET

    def test_thirty_two_symbols(self):
        assert len(ALPHABET) == 32
        assert len(set(ALPHABET)) == 32


class TestNormalize:
    def test_uppercases(self):
        assert normalize_code("abc234") == "ABC234"

    def test_strips_spaces_and_hyphens(self):
        assert normalize_code(" ABCD-2345 ") == "ABCD2345"

    def test_maps_ambiguous_letters(self):
        assert normalize_code("OIL0") == "0110"
        assert normalize_code("oil0") == "0110"

    def test_round_trips_generated_codes(self):
        for _ in range(50):
            code = generate_code()
            assert normalize_code(code) == code
            assert normalize_code(code.lower()) == code

    @pytest.mark.parametrize("bad", ["", "   ", "ABC!", "ABCU", "with space?"])
    def test_rejects_out_of_alphabet(self, bad):
        with pytest.raises(ValueError):
            normalize_code(bad)


class TestGenerate:
    def test_default_length(self):
        assert len(generate_code()) == CODE_LENGTH

    def test_alphabet_only(self):
        for _ in range(50):
            assert all(c in ALPHABET for c in generate_code())

    def test_no_trivial_repeats(self):
        assert len({generate_code() for _ in range(100)}) == 100


class TestNewUniqueCode:
    def test_retries_past_collisions(self, db_session, monkeypatch):
        """If generation collides with an existing row, the next attempt is
        used; only after every attempt collides does it give up."""
        from loobric_server.database.schema import Label
        taken = "TAKEN234"
        db_session.add(Label(code=taken, entity_type="tool_instance",
                             user_id="u", created_by="u", updated_by="u"))
        db_session.commit()

        codes = iter([taken, taken, "FRESH234"])
        monkeypatch.setattr(label_codes, "generate_code",
                            lambda length=CODE_LENGTH: next(codes))
        assert new_unique_code(db_session) == "FRESH234"

    def test_gives_up_after_attempts(self, db_session, monkeypatch):
        from loobric_server.database.schema import Label
        db_session.add(Label(code="STUCK234", entity_type="tool_instance",
                             user_id="u", created_by="u", updated_by="u"))
        db_session.commit()
        monkeypatch.setattr(label_codes, "generate_code",
                            lambda length=CODE_LENGTH: "STUCK234")
        with pytest.raises(RuntimeError):
            new_unique_code(db_session)
