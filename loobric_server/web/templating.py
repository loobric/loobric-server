# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only
"""Server-rendered HTML for the label resolver (`/t/{code}`).

The only templated HTML the server emits — the API stays JSON and the Web
UI stays a static file. Autoescape is on for everything: the public spec
page renders record-supplied strings (a tool's name) to anonymous visitors,
so escaping is a tested security assumption
(docs/SECURITY_ASSUMPTIONS.md), not a default we hope holds.
"""
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

_env = Environment(
    loader=FileSystemLoader(str(Path(__file__).parent / "templates")),
    autoescape=select_autoescape(enabled_extensions=("html", "xml"),
                                 default=True),
)


def render(template_name: str, **context) -> str:
    return _env.get_template(template_name).render(**context)
