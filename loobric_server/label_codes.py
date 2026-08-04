# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only
"""Short codes for physical labels (docs/LABELS.md).

A label carries a QR code AND the same short code printed human-readable —
the no-phone fallback: greasy hands, dead wifi, or no camera, and the code
can still be read off the sticker and typed into search.

Assumptions:
- Crockford base32 alphabet: no I, L, O, U, so a printed code has no
  0/O or 1/I/l ambiguity and no accidental English words.
- Codes are stored normalized (uppercase, canonical digits); every lookup
  normalizes its input first, so `t-7kx3 f9a` finds `T7KX3F9A`.
- Generation is `secrets`-random over 32^8 ≈ 1.1e12 — sparse enough that
  scanning the keyspace is impractical (see docs/SECURITY_ASSUMPTIONS.md),
  collision-retried against the labels.code UNIQUE index.
- The code is an opaque unique string, NOT structurally "a Loobric code":
  a future alias feature may register externally-issued codes (an existing
  asset tag) in the same column, so nothing outside this module may assume
  the alphabet.
"""
import secrets

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
CODE_LENGTH = 8

# Human-transcription fixups: the letters excluded from the alphabet map onto
# the digit they are most often mistaken for.
_AMBIGUOUS = str.maketrans({"O": "0", "I": "1", "L": "1"})


def normalize_code(raw: str) -> str:
    """Canonicalize a human- or scanner-supplied code.

    Uppercases, strips spaces and hyphens (sheets print codes grouped
    `ABCD-EFGH` for readability), and maps the ambiguous letters O/I/L to
    their canonical digits.

    Raises:
        ValueError: if the result is empty or contains characters outside
            the alphabet (including U, which is never issued).
    """
    code = (raw or "").strip().upper().replace(" ", "").replace("-", "")
    code = code.translate(_AMBIGUOUS)
    if not code or any(c not in ALPHABET for c in code):
        raise ValueError("not a valid label code: %r" % raw)
    return code


def generate_code(length: int = CODE_LENGTH) -> str:
    """A random code over the alphabet (already normalized by construction)."""
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def new_unique_code(db, length: int = CODE_LENGTH, attempts: int = 5) -> str:
    """Generate a code not present in the labels table.

    The existence check is a convenience; the labels.code UNIQUE index is the
    real guarantee (an astronomically-unlikely race surfaces as an
    IntegrityError, not a silent duplicate).
    """
    from loobric_server.database.schema import Label
    for _ in range(attempts):
        code = generate_code(length)
        if db.query(Label).filter(Label.code == code).first() is None:
            return code
    raise RuntimeError("could not generate a unique label code")
