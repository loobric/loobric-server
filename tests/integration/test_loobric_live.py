# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only
"""End-to-end integration tests: drive the loobric-cli reference client against
the REAL app in-process.

These prove the server accepts the client's requests and returns shapes the
client parses (the audit `logs` shape, empty-`{}` bodies, etc.) — things a mocked
unit suite can't catch. A transport bridge routes the client's requests through a
solo-mode TestClient (db_session-isolated), mirroring make_request's
success/error contract.

Requires the loobric-cli package (e.g. `pip install -e ../loobric-cli`);
skipped automatically when it isn't installed.
"""
import json

import pytest

pytest.importorskip("loobric")
import loobric.cli.main as cli_main      # noqa: E402
import loobric.transport as transport    # noqa: E402
from loobric.errors import _http_error    # noqa: E402



def _bridge(test_client):
    """A loobric-cli transport that calls the in-process app, mirroring make_request:
    parsed JSON on 2xx, the same LoobricClientError subclasses on error."""
    def transport(method, endpoint, body=None, extra_headers=None, require_auth=False,
                  base_url=None, api_key=None, session_cookie=None,
                  raw_body=None, content_type=None):
        url = "/api/v1/" + endpoint.lstrip("/")
        if raw_body is not None:
            headers = {"Content-Type": content_type} if content_type else {}
            resp = test_client.request(method, url, content=raw_body, headers=headers)
        else:
            resp = test_client.request(method, url, json=body)
        if 200 <= resp.status_code < 300:
            return resp.json() if resp.content else {}
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        raise _http_error(resp.status_code, detail)
    return transport


@pytest.fixture
def app_client(db_session, monkeypatch):
    monkeypatch.setenv("LOOBRIC_SOLO", "1")
    from fastapi.testclient import TestClient
    from loobric_server.main import create_app
    from loobric_server.api.auth import get_db
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c


@pytest.fixture
def cli(app_client, monkeypatch):
    """Route loobric-cli's command functions + Client through the in-process app, and
    return a bridged Client for tests that need raw ids."""
    bridge = _bridge(app_client)
    monkeypatch.setattr(cli_main, "_client", lambda: cli_main.Client(transport=bridge))
    monkeypatch.setattr(transport, "BASE_URL", "http://app")
    return cli_main.Client(transport=bridge)


# --------------------------------------------------------------------------
# The loop, end to end through the CLI command functions.
# --------------------------------------------------------------------------

@pytest.mark.integration
def test_full_loop_through_cli(cli, capsys):
    cli_main.create_machine("millstone", controller="linuxcnc")
    cli_main.push_table("millstone", ["3:1/4 downcut:6.35", "7:vee:6.0"])
    cli_main.show_tool_table("millstone")
    out = capsys.readouterr().out
    assert "T3" in out and "T7" in out and "unbound" in out

    cli_main.create_record_from_entry("millstone", 3, name="1/4 downcut")
    cli_main.show_tool_table("millstone")
    assert "bound ->" in capsys.readouterr().out

    cli_main.list_tools()
    assert "1/4 downcut" in capsys.readouterr().out


@pytest.mark.integration
def test_machines_and_sets(cli, capsys):
    cli_main.create_machine("millstone")
    cli_main.create_set("Drawer A")
    cli_main.link_machine("Drawer A", "millstone")
    cli_main.list_machines()
    assert "millstone" in capsys.readouterr().out
    cli_main.list_tool_sets()
    assert "Drawer A" in capsys.readouterr().out


@pytest.mark.integration
def test_bind_then_unbind(cli, capsys):
    cli_main.create_machine("m1")
    cli_main.push_table("m1", ["5:probe:3.0"])
    cli_main.create_record_from_entry("m1", 5, name="probe")
    cli_main.unbind_entry("m1", 5)
    cli_main.show_tool_table("m1")
    assert "unbound" in capsys.readouterr().out


@pytest.mark.integration
def test_inbox_lists_cleanly(cli, capsys):
    cli_main.list_pending()
    assert "Inbox is empty" in capsys.readouterr().out


@pytest.mark.integration
def test_audit_after_activity(cli, capsys):
    cli_main.create_machine("m1")
    capsys.readouterr()
    cli_main.list_audit()
    out = capsys.readouterr().out
    assert "CREATE" in out and "machine_record" in out


@pytest.mark.integration
def test_keys_lifecycle(cli, capsys):
    cli_main.create_key("k1", scopes="read")
    capsys.readouterr()
    cli_main.list_keys()
    out = capsys.readouterr().out
    assert "k1" in out and "active" in out


@pytest.mark.integration
def test_assert_door(cli, capsys):
    cli_main.create_set("S")
    capsys.readouterr()
    sid = cli.list_tool_sets()[0]["internal"]["id"]
    cli_main.assert_canonical("tool-set-records", sid, "name", "Renamed")
    assert "Asserted" in capsys.readouterr().out
    assert cli.get_tool_set(sid)["canonical"]["name"]["value"] == "Renamed"


@pytest.mark.integration
def test_observe_door(cli):
    cli_main.create_machine("m1")
    mid = cli.list_machines()[0]["internal"]["id"]
    cli.create_entry(mid)
    eid = cli.list_entries(mid)[0]["internal"]["id"]
    cli.observe_field("tool-table-entry-records", eid, "tool_number", 4,
                      client="linuxcnc", machine="m1")
    assert cli.get_entry(eid)["canonical"]["tool_number"]["value"] == 4


@pytest.mark.integration
def test_sync_client_section(cli):
    cli_main.create_set("S")
    sid = cli.list_tool_sets()[0]["internal"]["id"]
    cli.sync_client_section("tool-set-records", sid, "freecad", {"fctl": "x"})
    assert cli.get_tool_set(sid)["clients"]["freecad"]["data"] == {"fctl": "x"}


@pytest.mark.integration
def test_set_members(cli):
    cli_main.create_set("S")
    sid = cli.list_tool_sets()[0]["internal"]["id"]
    inst = cli.create_tool_record()
    iid = inst["internal"]["id"]
    cli.set_members(sid, [{"tool_record_id": iid, "number": 3}])
    members = cli.get_tool_set(sid)["canonical"]["members"]
    assert any(m["tool_record_id"] == iid for m in members)


@pytest.mark.integration
def test_add_and_remove_from_set_round_trip(cli):
    """add_to_set/remove_from_set against the live members door: add preserves
    existing members and skips duplicates; remove drops only the named tool."""
    cli_main.create_set("Drawer")
    sid = cli.list_tool_sets()[0]["internal"]["id"]
    a = cli.create_tool_record()["internal"]["id"]
    b = cli.create_tool_record()["internal"]["id"]

    cli.add_to_set(sid, [a])
    cli.add_to_set(sid, [a, b])                 # `a` already present -> not duplicated
    ids = [m["tool_record_id"] for m in cli.get_tool_set(sid)["canonical"]["members"]]
    assert sorted(ids) == sorted([a, b])
    assert ids.count(a) == 1

    cli.remove_from_set(sid, [a])
    ids = [m["tool_record_id"] for m in cli.get_tool_set(sid)["canonical"]["members"]]
    assert ids == [b]                           # only `a` removed, `b` kept


@pytest.mark.integration
def test_show_tool_set_renders_members(cli, capsys):
    cli_main.create_set("Drawer")
    sid = cli.list_tool_sets()[0]["internal"]["id"]
    inst = cli.create_tool_record()
    iid = inst["internal"]["id"]
    cli.set_members(sid, [{"tool_record_id": iid, "number": 5}])
    cli_main.show_tool_set(sid)
    out = capsys.readouterr().out
    assert "Tool Set" in out and "Members: 1" in out
    assert "T5" in out                          # the member's number, rendered
    assert iid[:8] in out or "(no #)" not in out  # the resolved tool, not a bare blank


@pytest.mark.integration
def test_catalog_records(cli):
    rec = cli.create_catalog_record(source="manufacturer:kennametal", fields={
        "name": {"value": "1/4in 2FL Endmill"},
        "manufacturer": {"value": "Kennametal"},
        "product_code": {"value": "B201"},
        "geometry": {"diameter": {"value": 6.35, "unit": "mm"}},
    })
    rid = rec["internal"]["id"]
    # The server stamps provenance — the client never wrote a `source`.
    assert rec["canonical"]["name"]["source"] == "asserted:manufacturer:kennametal"
    assert rec["canonical"]["geometry"]["diameter"]["source"] == \
        "asserted:manufacturer:kennametal"
    assert any(r["internal"]["id"] == rid for r in cli.list_catalog_records())
    assert cli.get_catalog_record(rid)["internal"]["id"] == rid


@pytest.mark.integration
def test_create_catalog_record_via_cli_stdin(cli, capsys, monkeypatch):
    """The acceptance path: JSON on stdin + --source -> a stamped record."""
    import io
    monkeypatch.setattr(cli_main.sys, "stdin",
                        io.StringIO('{"name": {"value": "Spot Drill"}, '
                                    '"manufacturer": {"value": "Acme"}, '
                                    '"product_code": {"value": "SD-90"}}'))
    cli_main.create_catalog_record(source="manufacturer:acme")
    out = capsys.readouterr().out
    assert "Spot Drill" in out and "asserted:manufacturer:acme" in out
    rec = cli.list_catalog_records()[0]
    assert rec["canonical"]["product_code"]["value"] == "SD-90"
    assert rec["canonical"]["product_code"]["source"] == "asserted:manufacturer:acme"


@pytest.mark.integration
def test_create_catalog_record_identity_floor(cli, monkeypatch):
    """Missing manufacturer/product_code -> the server rejects it (HTTP 400)."""
    import io
    monkeypatch.setattr(cli_main.sys, "stdin",
                        io.StringIO('{"name": {"value": "Nameless"}}'))
    with pytest.raises(cli_main.HTTPError):
        cli.create_catalog_record(source="human@cli",
                                  fields={"name": {"value": "Nameless"}})


@pytest.mark.integration
def test_catalog_resolver_by_product_code_and_ambiguity(cli, capsys):
    """The resolver accepts id/name/product_code; an ambiguous name prints
    candidates rather than guessing."""
    cli.create_catalog_record(source="manufacturer:acme", fields={
        "name": {"value": "Endmill"}, "manufacturer": {"value": "Acme"},
        "product_code": {"value": "A-100"}})
    cli.create_catalog_record(source="manufacturer:acme", fields={
        "name": {"value": "Endmill"}, "manufacturer": {"value": "Acme"},
        "product_code": {"value": "A-200"}})
    # Unique product_code resolves cleanly.
    cli_main.show_catalog_record("A-200")
    out = capsys.readouterr().out
    assert "A-200" in out and "asserted:manufacturer:acme" in out
    # The shared name is ambiguous -> candidates listed, no guess.
    with pytest.raises(SystemExit):
        cli_main.show_catalog_record("Endmill")
    err = capsys.readouterr().err
    assert "ambiguous" in err and "A-100" in err and "A-200" in err


@pytest.mark.integration
def test_create_record_from_catalog_makes_an_unbound_linked_instance(cli, capsys):
    """End to end (M2 #26): author a catalog record, then create-record
    --from-catalog -> a new UNBOUND instance that links the catalog type with
    requester-asserted provenance, measured geometry and status unknown."""
    cli.create_catalog_record(source="manufacturer:kennametal", fields={
        "name": {"value": "1/4in 2FL Endmill"},
        "manufacturer": {"value": "Kennametal"},
        "product_code": {"value": "B201"},
        "geometry": {"diameter": {"value": 6.35, "unit": "mm"}},
    })
    capsys.readouterr()

    cli_main.create_record_from_catalog("B201")          # resolve by product code
    out = capsys.readouterr().out
    assert "unbound" in out and "1/4in 2FL Endmill" in out

    instances = cli.list_tool_records()
    assert len(instances) == 1
    inst = instances[0]
    link = inst["canonical"]["catalog_type_id"]
    assert link["value"] and link["source"].startswith("asserted:")
    assert inst["canonical"]["geometry"] == {}          # measured geometry unknown
    # Unbound: no machine entry references it.
    assert cli.list_entries() == []


@pytest.mark.integration
def test_create_record_from_catalog_with_qa_stamps_manufacturer_provenance(
        cli, capsys, tmp_path):
    """End to end (M2 #27): create-record --from-catalog --qa qa.json --cert ->
    an UNBOUND instance whose MEASURED geometry carries observed:manufacturer@
    <serial> (the middle rung of the gradient — manufacturer QA, not the shop)."""
    cli.create_catalog_record(source="manufacturer:kennametal", fields={
        "name": {"value": "1/4in 2FL Endmill"},
        "manufacturer": {"value": "Kennametal"},
        "product_code": {"value": "B201"},
        "geometry": {"diameter": {"value": 6.35, "unit": "mm"}},
    })
    capsys.readouterr()
    qa = tmp_path / "qa.json"
    qa.write_text(json.dumps({"diameter": {"value": 6.34, "unit": "mm"},
                              "length": {"value": 50.0, "unit": "mm"}}))

    cli_main.create_record_from_catalog("B201", qa_path=str(qa),
                                       cert="kennametal@SN12345")
    out = capsys.readouterr().out
    assert "unbound" in out and "SN12345" in out

    inst = cli.list_tool_records()[0]
    geo = inst["canonical"]["geometry"]
    assert geo["diameter"]["value"] == 6.34
    assert geo["diameter"]["source"] == "observed:manufacturer@SN12345"
    assert geo["length"]["source"] == "observed:manufacturer@SN12345"


@pytest.mark.integration
def test_create_record_from_catalog_qa_requires_cert(cli, capsys, tmp_path):
    """--cert is required iff --qa: the QA file with no cert exits non-zero and
    creates no instance."""
    cli.create_catalog_record(source="manufacturer:acme", fields={
        "name": {"value": "Spot Drill"}, "manufacturer": {"value": "Acme"},
        "product_code": {"value": "SD-90"}})
    capsys.readouterr()
    qa = tmp_path / "qa.json"
    qa.write_text(json.dumps({"diameter": {"value": 3.0, "unit": "mm"}}))
    with pytest.raises(SystemExit):
        cli_main.create_record_from_catalog("SD-90", qa_path=str(qa), cert=None)
    assert "--qa requires --cert" in capsys.readouterr().err
    assert cli.list_tool_records() == []


@pytest.mark.integration
def test_create_record_from_catalog_twice_yields_two_instances(cli, capsys):
    """No dedup: each --from-catalog call mints a new, distinct instance."""
    cli.create_catalog_record(source="manufacturer:acme", fields={
        "name": {"value": "Spot Drill"}, "manufacturer": {"value": "Acme"},
        "product_code": {"value": "SD-90"}})
    capsys.readouterr()
    cli_main.create_record_from_catalog("SD-90")
    cli_main.create_record_from_catalog("SD-90")
    ids = {i["internal"]["id"] for i in cli.list_tool_records()}
    assert len(ids) == 2


@pytest.mark.integration
def test_changes_works_for_v2_records(cli):
    """Change-detection now operates on the v2 sectioned records (R12 fixed);
    the retired legacy entity types are no longer accepted."""
    assert cli.changes_max_version("tool_instance_records")["max_version"] == 0
    cli.create_tool_record()
    cli.create_tool_record()
    assert cli.changes_max_version("tool_instance_records")["max_version"] >= 1
    changed = cli.changes_since_version("tool_instance_records", 0)
    assert changed["count"] == 2
    with pytest.raises(cli_main.HTTPError):                  # legacy type -> 400
        cli.changes_max_version("tool_instances")


@pytest.mark.integration
def test_backup_export_runs(cli, capsys):
    cli_main.backup_export()
    out = capsys.readouterr().out
    assert "entities" in out or "metadata" in out


@pytest.mark.integration
def test_backup_roundtrip_captures_v2_data(cli, capsys):
    """R9: backup/restore now captures the v2 sectioned records (it used to back
    up only the empty legacy tables). Export -> wipe -> import restores them."""
    cli_main.create_machine("millstone", controller="linuxcnc")
    cli_main.push_table("millstone", ["3:downcut:6.35"])
    cli_main.create_record_from_entry("millstone", 3, name="downcut")
    capsys.readouterr()

    backup = cli.export_backup()
    assert len(backup["entities"]["machine_records"]) == 1
    assert len(backup["entities"]["tool_instance_records"]) == 1
    assert len(backup["entities"]["tool_table_entry_records"]) == 1

    cli.reset_account()
    assert cli.list_machines() == []

    cli.import_backup(json.dumps(backup))
    assert len(cli.list_machines()) == 1
    assert len(cli.list_tool_records()) == 1
    assert len(cli.list_entries()) == 1


@pytest.mark.integration
def test_reset_clears_tool_data(cli, capsys):
    cli_main.create_machine("m1")
    capsys.readouterr()
    cli_main.reset_account(assume_yes=True)
    capsys.readouterr()
    cli_main.list_machines()
    assert "No machines" in capsys.readouterr().out


@pytest.mark.integration
def test_whoami_works_in_solo(cli):
    # /auth/me now authenticates the same way as every other endpoint
    # (session / API key / solo), so in solo mode it returns the built-in solo
    # user instead of 401'ing. (It used to read only the session cookie, which
    # also broke API-key clients — see test_auth.test_auth_me_accepts_api_key.)
    me = cli.whoami()
    assert me["email"] == "solo@localhost.loobric_server"
