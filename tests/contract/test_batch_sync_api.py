# GNU Affero General Public License v3.0 only
# Copyright (c) 2026 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""Contract tests for the batch sync doors (docs/BATCH_SYNC.md, grilled
2026-08-17): POST /tool-instance-records/sync and
POST /tool-catalog-records/sync, plus the ratified same-value rule the
single-record assert doors adopted with them."""
import pytest

BASE = "/api/v1"
INSTANCES = f"{BASE}/tool-instance-records"
CATALOGS = f"{BASE}/tool-catalog-records"


def _item(item_id="guid-1", name="mysterybit", diameter=5.0, **over):
    item = {
        "client_item_id": item_id,
        "data": {"tool": {"guid": item_id, "description": name}},
        "asserts": [
            {"path": "name", "value": name},
            {"path": "geometry.diameter", "value": diameter, "unit": "mm"},
            {"path": "geometry.shape", "value": "ballend"},
        ],
    }
    item.update(over)
    return item


def _batch(items, client="fusion360", **over):
    body = {"client": client, "client_version": "0.2.0", "items": items}
    body.update(over)
    return body


# -- instance door -----------------------------------------------------------

def test_instance_batch_creates_with_asserts_and_seeds_section(solo_client):
    r = solo_client.post(f"{INSTANCES}/sync",
                         json=_batch([_item("g-1"), _item("g-2", "probe")]))
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [i["result"] for i in items] == ["created", "created"]
    assert all(i["asserts_applied"] == 3 for i in items)
    rec = solo_client.get(f"{INSTANCES}/{items[0]['id']}").json()
    assert rec["canonical"]["name"] == {
        "value": "mysterybit", "source": "asserted:fusion360"}
    assert rec["canonical"]["geometry"]["diameter"]["unit"] == "mm"
    section = rec["clients"]["fusion360"]
    assert section["client_item_id"] == "g-1"
    assert section["data"]["tool"]["description"] == "mysterybit"


def test_instance_batch_is_idempotent(solo_client):
    body = _batch([_item("g-1")])
    first = solo_client.post(f"{INSTANCES}/sync", json=body).json()["items"][0]
    version = solo_client.get(
        f"{INSTANCES}/{first['id']}").json()["internal"]["version"]
    again = solo_client.post(f"{INSTANCES}/sync", json=body).json()["items"][0]
    assert again["result"] == "unchanged"
    assert again["asserts_applied"] == 0          # same value+actor = no-op
    assert again["id"] == first["id"]
    after = solo_client.get(
        f"{INSTANCES}/{first['id']}").json()["internal"]["version"]
    assert after == version                        # zero churn end to end


def test_instance_batch_updates_changed_data_and_asserts(solo_client):
    rid = solo_client.post(f"{INSTANCES}/sync", json=_batch(
        [_item("g-1")])).json()["items"][0]["id"]
    changed = _item("g-1", diameter=6.35)
    changed["data"]["tool"]["description"] = "renamed"
    out = solo_client.post(f"{INSTANCES}/sync",
                           json=_batch([changed])).json()["items"][0]
    assert out["result"] == "updated"
    assert out["asserts_applied"] == 1             # only the diameter changed
    rec = solo_client.get(f"{INSTANCES}/{rid}").json()
    assert rec["canonical"]["geometry"]["diameter"]["value"] == 6.35
    assert rec["clients"]["fusion360"]["data"]["tool"]["description"] \
        == "renamed"


def test_same_value_different_actor_still_applies(solo_client):
    rid = solo_client.post(f"{INSTANCES}/sync", json=_batch(
        [_item("g-1")])).json()["items"][0]["id"]
    out = solo_client.post(
        f"{INSTANCES}/sync",
        json=_batch([_item("g-1")], actor="qc-agent")).json()["items"][0]
    assert out["asserts_applied"] == 3             # corroboration recorded
    rec = solo_client.get(f"{INSTANCES}/{rid}").json()
    assert rec["canonical"]["name"]["source"] == "asserted:qc-agent"


def test_instance_batch_identity_errors(solo_client):
    r = solo_client.post(f"{INSTANCES}/sync", json=_batch([
        {"data": {"x": 1}},                                  # no identity
        {"id": "no-such-record", "data": {}},                # unknown id
        _item("g-ok"),
    ]))
    items = r.json()["items"]
    assert "needs `id` or `client_item_id`" in items[0]["error"]
    assert "unknown id" in items[1]["error"]
    assert items[2]["result"] == "created"         # the batch proceeded


def test_instance_batch_ambiguous_item_id(solo_client):
    for _ in range(2):                              # two records, same item id
        solo_client.post(INSTANCES, json={
            "client": "fusion360", "client_item_id": "dup",
            "data": {"n": 1}})
    out = solo_client.post(f"{INSTANCES}/sync", json=_batch(
        [_item("dup")])).json()["items"][0]
    assert out["result"] == "error"
    assert "ambiguous_item_id" in out["error"]


def test_instance_batch_guard_violation_leaves_item_untouched(solo_client):
    bad = _item("g-guarded")
    bad["asserts"].append({"path": "presets", "value": []})
    out = solo_client.post(f"{INSTANCES}/sync",
                           json=_batch([bad])).json()["items"][0]
    assert out["result"] == "error"
    assert "derived union" in out["error"]
    assert out["id"] is None                       # nothing was created
    listing = solo_client.get(INSTANCES).json()["items"]
    assert all((r["clients"].get("fusion360") or {}).get("client_item_id")
               != "g-guarded" for r in listing)


def test_instance_batch_presets_contribute_and_floor_skip(solo_client):
    item = _item("g-p")
    item["presets"] = [
        {"origin": "fusion360", "label": "Default preset",
         "material": {"name": "all"},
         "vc": {"value": 78.54, "unit": "m/min"}},
        {"origin": "fusion360", "label": "no values",
         "material": {"name": "all"}},             # below the floor
    ]
    out = solo_client.post(f"{INSTANCES}/sync",
                           json=_batch([item])).json()["items"][0]
    assert out["presets_contributed"] == 1
    assert out["presets_skipped"] == 1
    rec = solo_client.get(f"{INSTANCES}/{out['id']}").json()
    [entry] = rec["canonical"]["presets"]["value"]
    assert entry["label"] == "Default preset"
    assert entry["source"] == "asserted:fusion360"


def test_instance_batch_cap_is_413(solo_client):
    items = [_item("g-%d" % i) for i in range(201)]
    r = solo_client.post(f"{INSTANCES}/sync", json=_batch(items))
    assert r.status_code == 413
    assert "chunk" in r.json()["detail"]


def test_instance_batch_include_records(solo_client):
    r = solo_client.post(f"{INSTANCES}/sync?include=records",
                         json=_batch([_item("g-1")]))
    [out] = r.json()["items"]
    assert out["record"]["internal"]["id"] == out["id"]
    assert out["record"]["canonical"]["name"]["value"] == "mysterybit"


def test_instance_batch_rejects_out_of_lane_item(solo_client):
    r = solo_client.post(f"{INSTANCES}/sync", json=_batch(
        [{"client_item_id": "g-1", "data": {},
          "canonical": {"name": {"value": "smuggled"}}}]))
    assert r.status_code == 422                    # extra=forbid IS the lane


def test_instance_batch_audit_trail(solo_client):
    solo_client.post(f"{INSTANCES}/sync", json=_batch([_item("g-1")]))
    rows = solo_client.get(f"{BASE}/audit-logs").json()["logs"]
    ops = [r["operation"] for r in rows]
    assert "SYNC_BATCH" in ops
    assert "CREATE" in ops and "ASSERT" in ops
    batch_row = next(r for r in rows if r["operation"] == "SYNC_BATCH")
    assert batch_row["changes"]["created"] == 1


# -- scope composition -------------------------------------------------------

def _register_and_login(client, email="batch@test.io"):
    client.post(f"{BASE}/auth/register",
                json={"email": email, "password": "p" * 12})
    r = client.post(f"{BASE}/auth/login",
                    json={"email": email, "password": "p" * 12})
    assert r.status_code == 200, r.text
    return client


def _key(client, scopes, name="k"):
    r = client.post(f"{BASE}/auth/keys", json={"name": name, "scopes": scopes})
    assert r.status_code == 201, r.text
    return {"Authorization": "Bearer " + r.json()["key"]}


def test_sync_only_key_gets_blocked_counts_never_a_rejected_batch(client):
    _register_and_login(client)
    sync_only = _key(client, ["read", "sync"], "sync-only")
    full = _key(client, ["read", "sync", "assert"], "cam")
    client.cookies.clear()

    # A sync-only key cannot CREATE (creation is assert territory) …
    out = client.post(f"{INSTANCES}/sync", headers=sync_only,
                      json=_batch([_item("g-1")])).json()["items"][0]
    assert out["result"] == "error" and "assert scope" in out["error"]

    # … but against an existing record it syncs data and gets blocked/skipped
    # counts for the assert-lane payloads — never a 403 on the batch.
    made = client.post(f"{INSTANCES}/sync", headers=full,
                       json=_batch([_item("g-1")])).json()["items"][0]
    assert made["result"] == "created"
    item = _item("g-1")
    item["data"]["tool"]["description"] = "edited"
    item["presets"] = [{"origin": "fusion360", "label": "p",
                        "material": {"name": "all"},
                        "vc": {"value": 1, "unit": "m/min"}}]
    r = client.post(f"{INSTANCES}/sync", headers=sync_only,
                    json=_batch([item]))
    assert r.status_code == 200
    out = r.json()["items"][0]
    assert out["result"] == "updated"
    assert out["asserts_blocked"] == 3
    assert out["presets_skipped"] == 1 and out["presets_contributed"] == 0


# -- catalog door ------------------------------------------------------------

def _catalog_item(pc="46211-K", data=None):
    return {
        "client_item_id": pc,
        "data": data or {"format": "fusion-tools", "raw": {"pc": pc}},
        "asserts": [
            {"path": "name", "value": "Spektra endmill %s" % pc},
            {"path": "manufacturer", "value": "Amana Tool"},
            {"path": "product_code", "value": pc},
            {"path": "geometry.diameter", "value": 6.35, "unit": "mm"},
        ],
        "presets": [
            {"origin": "manufacturer", "label": "hardwood",
             "material": {"name": "hardwood"},
             "vc": {"value": 900, "unit": "ft/min"}},
        ],
    }


def test_catalog_batch_creates_seeded(solo_client):
    r = solo_client.post(f"{CATALOGS}/sync",
                         json=_batch([_catalog_item()], client="cli",
                                     actor="amana"))
    assert r.status_code == 200, r.text
    [out] = r.json()["items"]
    assert out["result"] == "created"
    assert out["presets_contributed"] == 1
    rec = solo_client.get(f"{CATALOGS}/{out['id']}").json()
    assert rec["canonical"]["manufacturer"]["source"] == "asserted:amana"
    [entry] = rec["canonical"]["presets"]["value"]
    assert entry["origin"] == "manufacturer"
    assert rec["clients"]["cli"]["data"]["format"] == "fusion-tools"


def test_catalog_batch_exists_syncs_own_section_only(solo_client):
    solo_client.post(f"{CATALOGS}/sync",
                     json=_batch([_catalog_item()], client="cli",
                                 actor="amana"))
    newer = _catalog_item(data={"format": "fusion-tools", "raw": {"v": 2}})
    newer["asserts"][3] = {"path": "geometry.diameter", "value": 9.99,
                           "unit": "mm"}          # must NOT land
    [out] = solo_client.post(
        f"{CATALOGS}/sync",
        json=_batch([newer], client="cli", actor="amana")).json()["items"]
    assert out["result"] == "exists"
    assert out["asserts_applied"] == 0
    assert out["presets_contributed"] == 0
    rec = solo_client.get(f"{CATALOGS}/{out['id']}").json()
    assert rec["canonical"]["geometry"]["diameter"]["value"] == 6.35
    assert rec["clients"]["cli"]["data"]["raw"] == {"v": 2}   # raw refreshed


def test_catalog_batch_identity_floor(solo_client):
    item = _catalog_item()
    item["asserts"] = [a for a in item["asserts"]
                       if a["path"] != "manufacturer"]
    [out] = solo_client.post(
        f"{CATALOGS}/sync",
        json=_batch([item], client="cli")).json()["items"]
    assert out["result"] == "error"
    assert "identity floor" in out["error"]


def test_catalog_batch_in_batch_duplicate_is_exists(solo_client):
    r = solo_client.post(f"{CATALOGS}/sync", json=_batch(
        [_catalog_item("PC-1"), _catalog_item("PC-1")], client="cli"))
    results = [i["result"] for i in r.json()["items"]]
    assert results == ["created", "exists"]


# -- the single doors adopted the same-value rule ----------------------------

def test_single_assert_door_same_value_noop(solo_client):
    rid = solo_client.post(INSTANCES, json={}).json()["internal"]["id"]
    body = {"path": "geometry.diameter", "value": 5, "unit": "mm",
            "actor": "fusion360"}
    v1 = solo_client.post(f"{INSTANCES}/{rid}/assert",
                          json=body).json()["internal"]["version"]
    v2 = solo_client.post(f"{INSTANCES}/{rid}/assert",
                          json=body).json()["internal"]["version"]
    assert v2 == v1                                # same actor: no-op
    other = dict(body, actor="qc-agent")
    r3 = solo_client.post(f"{INSTANCES}/{rid}/assert", json=other).json()
    assert r3["internal"]["version"] == v1 + 1     # different actor: applies
    assert r3["canonical"]["geometry"]["diameter"]["source"] \
        == "asserted:qc-agent"
