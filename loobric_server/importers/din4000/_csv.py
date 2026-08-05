# MIT License
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: MIT
"""DIN 4000 CSV front-end: a semicolon-delimited table → ``{code: value}`` rows.

The header row is DIN 4000 feature codes; each subsequent row is one tool. Uses
the stdlib ``csv`` reader (not ``split(';')``) because values can be quoted with
embedded commas, e.g. ``"FZI,FSE,FNU,FEC"``. Semicolon is the delimiter (comma
is a decimal/grouping character in this data); a trailing ``;`` produces an empty
final column, which is ignored.
"""
import csv
import io
from typing import Dict, List


def parse_csv(text: str) -> List[Dict[str, str]]:
    reader = csv.reader(io.StringIO(text), delimiter=";")
    rows = [r for r in reader if any(cell.strip() for cell in r)]
    if not rows:
        return []
    header = [h.strip() for h in rows[0]]
    out: List[Dict[str, str]] = []
    for row in rows[1:]:
        record: Dict[str, str] = {}
        for code, value in zip(header, row):
            if code:                      # skip the empty trailing-delimiter column
                record[code] = value.strip()
        out.append(record)
    return out
