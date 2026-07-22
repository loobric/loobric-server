# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Contract tests for the sectioned ToolCatalogRecord facade.

Mirrors the ToolInstanceRecord tracer: responses are the three-section shape and
validate against loobric_server.contract; a client writes only its own section; routine
sync cannot touch internal/canonical. The one difference: a catalog TYPE carries
nominal, asserted data — there is no observe door, because a machine never
measures a type. See docs/TOOL_SCHEMA.md §7.1.

Create is **seeded and atomic** (M2, issue #24): one declared actor plus the
nominal {value, unit} fields, and the server stamps `asserted:<actor>` on each
(the client never writes provenance). Identity floor: name/manufacturer/
product_code are required; spec fields stay honest-sparse.
"""
import pytest
from sqlalchemy.exc import IntegrityError

from loobric_server.contract import ToolCatalogRecord, ToolInstanceRecord
from loobric_server.database.schema import AuditLog
from loobric_server.database.schema import ToolCatalogRecord as Row

BASE = "/api/v1/tool-catalog-records"
INSTANCE_BASE = "/api/v1/tool-instance-records"
ENTRY_BASE = "/api/v1/tool-table-entry-records"


def conforms(doc):
    """The server's own output validates against the published contract."""
    ToolCatalogRecord.model_validate(doc)
    return doc


def seed(solo_client, actor="manufacturer:kennametal", **overrides):
    """POST a valid identity-floored create and return the conformant record."""
    body = {
        "actor": actor,
        "name": {"value": "1/4in 2FL Endmill"},
        "manufacturer": {"value": "Kennametal"},
        "product_code": {"value": "B201"},
    }
    body.update(overrides)
    r = solo_client.post(BASE, json=body)
    assert r.status_code == 200, r.text
    return conforms(r.json())


@pytest.mark.contract
def test_seeded_create_stamps_asserted_provenance_on_every_field(solo_client):
    """The acceptance tracer: one declared actor seeds every field, and the
    server — not the client — stamps asserted:<actor> as its source."""
    doc = seed(solo_client, actor="manufacturer:kennametal",
               geometry={"diameter": {"value": 6.35, "unit": "mm"},
                         "flutes": {"value": 2}})
    assert doc["internal"]["version"] == 1 and doc["internal"]["id"]
    src = "asserted:manufacturer:kennametal"
    for path in (("name",), ("manufacturer",), ("product_code",),
                 ("geometry", "diameter"), ("geometry", "flutes")):
        leaf = doc["canonical"]
        for p in path:
            leaf = leaf[p]
        assert leaf["source"] == src, path
    assert doc["canonical"]["geometry"]["diameter"]["value"] == 6.35
    assert doc["canonical"]["geometry"]["diameter"]["unit"] == "mm"


@pytest.mark.contract
@pytest.mark.parametrize("missing", ["name", "manufacturer", "product_code"])
def test_create_requires_the_identity_floor(solo_client, missing):
    """Missing any of name/manufacturer/product_code is rejected — findability,
    not spec completeness."""
    body = {
        "actor": "human@cli",
        "name": {"value": "x"},
        "manufacturer": {"value": "Acme"},
        "product_code": {"value": "P1"},
    }
    del body[missing]
    r = solo_client.post(BASE, json=body)
    assert r.status_code == 400, r.text
    assert missing in r.text


@pytest.mark.contract
def test_identity_floor_rejects_a_null_value(solo_client):
    """A present-but-null identity field is as missing as an absent one."""
    r = solo_client.post(BASE, json={
        "actor": "human@cli", "name": {"value": None},
        "manufacturer": {"value": "Acme"}, "product_code": {"value": "P1"}})
    assert r.status_code == 400, r.text


@pytest.mark.contract
def test_create_accepts_sparse_spec(solo_client):
    """A record with no geometry is honest, not invalid — never fabricate fields
    to pass a gate."""
    doc = seed(solo_client)
    assert doc["canonical"]["geometry"] == {}


@pytest.mark.contract
def test_client_cannot_supply_source(solo_client):
    """Lane discipline: a field that smuggles in its own `source` is rejected —
    provenance is the server's to stamp, never the client's to write."""
    r = solo_client.post(BASE, json={
        "actor": "human@cli",
        "name": {"value": "x", "source": "asserted:somebody-else"},
        "manufacturer": {"value": "Acme"}, "product_code": {"value": "P1"}})
    assert r.status_code == 422, r.text


@pytest.mark.contract
def test_create_is_atomic_and_writes_one_audit_row(solo_client, db_session):
    """All-or-nothing: a malformed seed leaves no half-built record and no audit
    row; a success writes exactly one CREATE row."""
    def created_rows():
        return db_session.query(AuditLog).filter_by(
            entity_type="tool_catalog_record", operation="CREATE").count()
    before = created_rows()

    # Malformed: past pydantic + the identity floor, but an invalid item_type
    # fails canonical validation — rejected before any DB write.
    bad = solo_client.post(BASE, json={
        "actor": "human@cli", "name": {"value": "x"},
        "manufacturer": {"value": "Acme"}, "product_code": {"value": "P1"},
        "item_type": {"value": "not-a-real-type"}})
    assert bad.status_code == 400, bad.text
    assert db_session.query(Row).count() == 0      # no half-built record
    assert created_rows() == before                # no audit row

    seed(solo_client)
    assert created_rows() == before + 1            # exactly one


@pytest.mark.contract
def test_create_can_seed_an_initial_client_section(solo_client):
    doc = seed(solo_client, client="catalog-import", client_version="1.2.0",
               client_item_id="harvey-12345", client_data={"raw": {"page": 42}})
    sec = doc["clients"]["catalog-import"]
    assert sec["client_version"] == "1.2.0" and sec["client_item_id"] == "harvey-12345"
    assert sec["created_at"] and sec["updated_at"]          # server-stamped
    assert "client" not in sec                               # identity is the map key
    assert sec["data"]["raw"]["page"] == 42


@pytest.mark.contract
def test_sync_writes_only_the_client_section(solo_client):
    rid = seed(solo_client)["internal"]["id"]
    r = solo_client.put(f"{BASE}/{rid}/clients/catalog-import",
                        json={"client_version": "1.2.0", "client_item_id": "harvey-12345",
                              "data": {"any": [1, 2]}})
    assert r.status_code == 200, r.text
    doc = conforms(r.json())
    assert doc["clients"]["catalog-import"]["data"] == {"any": [1, 2]}
    assert doc["internal"]["version"] == 2                   # bumped


@pytest.mark.contract
@pytest.mark.parametrize("forbidden", ["internal", "canonical", "client"])
def test_sync_cannot_touch_internal_or_canonical(solo_client, forbidden):
    """The load-bearing safety property, enforced at the API: a sync write that
    reaches for internal/canonical (or re-sends the redundant `client` key) is a
    loud 400, not a silent strip."""
    rid = seed(solo_client)["internal"]["id"]
    body = {"client_version": "1.2.0", "data": {}}
    body[forbidden] = "x" if forbidden == "client" else {"name": "endmill"}
    r = solo_client.put(f"{BASE}/{rid}/clients/catalog-import", json=body)
    assert r.status_code == 400, r.text


# ---------------------------------------------------------------------------
# Natural-key uniqueness — the 409 reuse funnel (M2, issue #25).
# Key: (user_id, manufacturer, product_code), per-account, trim+casefold.
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_duplicate_create_is_409_naming_the_existing_record(solo_client):
    """A second record on the same natural key for one account is refused — and
    the 409 names the existing record's id, inviting reuse, not a bare dup error."""
    first = seed(solo_client)                       # Kennametal / B201
    eid = first["internal"]["id"]
    r = solo_client.post(BASE, json={
        "actor": "human@cli", "name": {"value": "another label"},
        "manufacturer": {"value": "Kennametal"}, "product_code": {"value": "B201"}})
    assert r.status_code == 409, r.text
    assert eid in r.text                            # names the existing record
    assert "create an instance from it" in r.text   # the funnel, not a dead end


@pytest.mark.contract
@pytest.mark.parametrize("manufacturer,product_code", [
    ("kennametal", "B201"),        # lowercase manufacturer
    ("KENNAMETAL", "b201"),        # uppercase manufacturer, lowercase code
    ("  Kennametal  ", " B201 "),  # surrounding whitespace on both
])
def test_casing_and_whitespace_variants_collide(solo_client, manufacturer, product_code):
    """trim + casefold: every variant of (Kennametal, B201) is the SAME key."""
    seed(solo_client)                               # canonical Kennametal / B201
    r = solo_client.post(BASE, json={
        "actor": "human@cli", "name": {"value": "x"},
        "manufacturer": {"value": manufacturer},
        "product_code": {"value": product_code}})
    assert r.status_code == 409, r.text


@pytest.mark.contract
def test_create_preserves_the_unnormalized_display_value(solo_client):
    """Normalization is for comparison only — the original display value is stored
    unchanged (whitespace and casing as the author typed them)."""
    doc = seed(solo_client,
               manufacturer={"value": "  Kennametal  "},
               product_code={"value": " B-77 "})
    assert doc["canonical"]["manufacturer"]["value"] == "  Kennametal  "
    assert doc["canonical"]["product_code"]["value"] == " B-77 "


@pytest.mark.contract
def test_assert_into_a_collision_is_rejected_by_the_same_index(solo_client):
    """The assert door shares the create door's enforcement: editing a record's
    manufacturer/product_code into another record's key is a 409 naming it."""
    a = seed(solo_client, manufacturer={"value": "Acme"},
             product_code={"value": "P1"})["internal"]["id"]
    b = seed(solo_client, manufacturer={"value": "Beta"},
             product_code={"value": "P2"})["internal"]["id"]
    # Step b toward a's key: manufacturer first (Acme/P2 — not yet a collision).
    r1 = solo_client.post(f"{BASE}/{b}/assert",
                          json={"path": "manufacturer", "value": "Acme",
                                "actor": "human@cli"})
    assert r1.status_code == 200, r1.text
    # Now the product_code edit lands b on Acme/P1 — collision with a.
    r2 = solo_client.post(f"{BASE}/{b}/assert",
                          json={"path": "product_code", "value": "P1",
                                "actor": "human@cli"})
    assert r2.status_code == 409, r2.text
    assert a in r2.text
    # The edit was rolled back: b still has its prior product_code.
    after = conforms(solo_client.get(f"{BASE}/{b}").json())
    assert after["canonical"]["product_code"]["value"] == "P2"


def test_natural_key_is_scoped_per_account(db_session):
    """Two accounts may each hold the same (manufacturer, product_code); a second
    record on one account's key violates the unique index. Exercised at the DB
    layer because the index — not a query — is the enforcement (solo mode is a
    single account)."""
    def mk(uid):
        canonical = {
            "name": {"value": "x", "source": "asserted:t"},
            "manufacturer": {"value": "Kennametal", "source": "asserted:t"},
            "product_code": {"value": "B201", "source": "asserted:t"},
            "geometry": {},
        }
        row = Row(canonical=canonical, clients={},
                  user_id=uid, created_by=uid, updated_by=uid)
        row.manufacturer_norm = "kennametal"     # trim+casefold of "Kennametal"
        row.product_code_norm = "b201"
        return row

    db_session.add(mk("acct-a"))
    db_session.commit()
    db_session.add(mk("acct-b"))     # different account, same key: allowed
    db_session.commit()
    assert db_session.query(Row).count() == 2

    db_session.add(mk("acct-a"))                          # same account: refused
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


# ---------------------------------------------------------------------------
# The catalog -> instance door (M2, issue #26): a deliberate, audited create
# that links the catalog type and leaves the instance UNBOUND. No "mint" wording.
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_create_instance_links_catalog_with_asserted_requester_provenance(solo_client):
    """The link is the requester's own first-party act: the new instance asserts
    catalog_type_id = the catalog id, source asserted:<requester> — the actor
    defaults to the requesting context, never a client field. The name is copied
    from the catalog and is likewise requester-asserted."""
    rid = seed(solo_client)["internal"]["id"]
    r = solo_client.post(f"{BASE}/{rid}/create-instance", json={})
    assert r.status_code == 200, r.text
    doc = r.json()
    ToolInstanceRecord.model_validate(doc)          # conforms to the instance contract
    link = doc["canonical"]["catalog_type_id"]
    assert link["value"] == rid
    assert link["source"].startswith("asserted:")   # requester-asserted, not unknown
    name = doc["canonical"]["name"]
    assert name["value"] == "1/4in 2FL Endmill"      # copied from the catalog
    assert name["source"].startswith("asserted:")


@pytest.mark.contract
def test_create_instance_is_unbound_with_unknown_geometry_and_status(solo_client):
    """The post-condition: no QA (measured geometry unknown), status unknown, and
    bound to no machine entry — a catalog is not a machine position."""
    rid = seed(solo_client)["internal"]["id"]
    doc = solo_client.post(f"{BASE}/{rid}/create-instance", json={}).json()
    iid = doc["internal"]["id"]
    assert doc["canonical"]["geometry"] == {}        # no measured geometry (no QA)
    status = doc["canonical"].get("status")
    assert status is None or status["value"] is None  # status unknown
    # Bound to no entry: no tool-table entry references this instance.
    entries = solo_client.get(ENTRY_BASE).json()["items"]
    assert all((e["canonical"].get("bound_instance_id") or {}).get("value") != iid
               for e in entries)


@pytest.mark.contract
def test_create_instance_name_override(solo_client):
    """A request name overrides the copied catalog name (still requester-asserted)."""
    rid = seed(solo_client)["internal"]["id"]
    doc = solo_client.post(f"{BASE}/{rid}/create-instance",
                           json={"name": "shop relabel"}).json()
    assert doc["canonical"]["name"]["value"] == "shop relabel"
    assert doc["canonical"]["name"]["source"].startswith("asserted:")


@pytest.mark.contract
def test_each_call_yields_a_distinct_instance(solo_client):
    """Two identical tools = two instances pointing at one type. No dedup: calling
    twice on the same catalog yields two different instance ids."""
    rid = seed(solo_client)["internal"]["id"]
    a = solo_client.post(f"{BASE}/{rid}/create-instance", json={}).json()
    b = solo_client.post(f"{BASE}/{rid}/create-instance", json={}).json()
    assert a["internal"]["id"] != b["internal"]["id"]
    assert a["canonical"]["catalog_type_id"]["value"] == rid
    assert b["canonical"]["catalog_type_id"]["value"] == rid
    # both are real, distinct instances on the instance resource
    ids = {i["internal"]["id"] for i in solo_client.get(INSTANCE_BASE).json()["items"]}
    assert {a["internal"]["id"], b["internal"]["id"]} <= ids


@pytest.mark.contract
def test_create_instance_404_when_catalog_absent(solo_client):
    """A catalog id that isn't found/owned is a 404."""
    r = solo_client.post(f"{BASE}/does-not-exist/create-instance", json={})
    assert r.status_code == 404, r.text


def test_create_instance_endpoint_introduces_no_mint_wording():
    """The catalog->instance flow uses neutral 'create instance' language — no
    'mint' anywhere in the endpoint or its docstring (the entry-adopt flow
    elsewhere legitimately still mints; this door does not)."""
    import inspect
    from loobric_server.api import tool_catalog_records as mod
    assert "mint" not in inspect.getsource(mod.create_instance_from_catalog).lower()


# ---------------------------------------------------------------------------
# Manufacturer QA at instance creation (M2, issue #27): the middle rung of the
# provenance gradient. The audited catalog->instance door is permitted to stamp a
# third-party observed:manufacturer@<cert> on measured geometry; the routine
# observe door is unchanged and only ever stamps the client's OWN identity.
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_create_instance_qa_stamps_observed_manufacturer_provenance(solo_client):
    """QA payload + cert -> each measured-geometry field carries
    observed:manufacturer@<serial>. The WHO is the generic 'manufacturer' role; the
    WHERE/serial is the tail of cert after the last '@', so 'kennametal@SN12345'
    yields observed:manufacturer@SN12345. The client sends only values+units+cert;
    the SERVER composes the source (lane discipline)."""
    rid = seed(solo_client)["internal"]["id"]
    r = solo_client.post(f"{BASE}/{rid}/create-instance", json={
        "qa": {"diameter": {"value": 6.34, "unit": "mm"},
               "length": {"value": 50.0, "unit": "mm"}},
        "cert": "kennametal@SN12345",
    })
    assert r.status_code == 200, r.text
    doc = r.json()
    ToolInstanceRecord.model_validate(doc)
    geo = doc["canonical"]["geometry"]
    assert geo["diameter"]["value"] == 6.34 and geo["diameter"]["unit"] == "mm"
    assert geo["diameter"]["source"] == "observed:manufacturer@SN12345"
    assert geo["length"]["source"] == "observed:manufacturer@SN12345"


@pytest.mark.contract
def test_create_instance_qa_cert_serial_only_also_works(solo_client):
    """A bare serial cert (no vendor prefix) yields the same who=manufacturer
    source — the serial tail is taken after the last '@', and absent any '@' the
    whole cert is the serial."""
    rid = seed(solo_client)["internal"]["id"]
    doc = solo_client.post(f"{BASE}/{rid}/create-instance", json={
        "qa": {"diameter": {"value": 6.34, "unit": "mm"}},
        "cert": "SN999",
    }).json()
    assert doc["canonical"]["geometry"]["diameter"]["source"] == \
        "observed:manufacturer@SN999"


@pytest.mark.contract
def test_create_instance_qa_without_cert_is_rejected(solo_client):
    """cert is REQUIRED when QA geometry is present (a measurement with no
    certificate to record it against is rejected, not silently un-sourced)."""
    rid = seed(solo_client)["internal"]["id"]
    r = solo_client.post(f"{BASE}/{rid}/create-instance", json={
        "qa": {"diameter": {"value": 6.34, "unit": "mm"}}})
    assert r.status_code == 400, r.text
    assert "cert" in r.json()["detail"]


@pytest.mark.contract
def test_create_instance_cert_without_qa_is_rejected(solo_client):
    """The documented decision: a cert with no QA to certify is a 400 (symmetric
    with qa-without-cert), never a silent no-op."""
    rid = seed(solo_client)["internal"]["id"]
    r = solo_client.post(f"{BASE}/{rid}/create-instance", json={
        "cert": "kennametal@SN12345"})
    assert r.status_code == 400, r.text


@pytest.mark.contract
def test_create_instance_no_qa_leaves_measured_geometry_unknown(solo_client):
    """#26 regression: with no QA the instance's measured geometry is empty
    (unknown) — QA is strictly additive."""
    rid = seed(solo_client)["internal"]["id"]
    doc = solo_client.post(f"{BASE}/{rid}/create-instance", json={}).json()
    assert doc["canonical"]["geometry"] == {}


@pytest.mark.contract
def test_third_party_manufacturer_provenance_is_a_catalog_door_carveout(solo_client):
    """The carve-out: the audited catalog->instance door CAN stamp a third-party
    observed:manufacturer@<serial>. The routine observe door is the contrast — it
    composes the source from the client's OWN declared (client, machine) envelope,
    so it can only ever stamp the client's own identity, never a foreign
    'manufacturer' who. (observe is unchanged; see
    test_tool_instance_records_api.test_observe_sets_a_measured_field_from_a_machine.)"""
    rid = seed(solo_client)["internal"]["id"]
    # Audited door: a third-party 'manufacturer' who is permitted here.
    inst = solo_client.post(f"{BASE}/{rid}/create-instance", json={
        "qa": {"diameter": {"value": 6.34, "unit": "mm"}},
        "cert": "kennametal@SN12345"}).json()
    iid = inst["internal"]["id"]
    assert inst["canonical"]["geometry"]["diameter"]["source"] == \
        "observed:manufacturer@SN12345"
    # Routine observe door: source is the client's OWN identity, not a third party.
    obs = solo_client.post(f"{INSTANCE_BASE}/{iid}/observe", json={
        "path": "geometry.diameter", "value": 6.35, "unit": "mm",
        "client": "linuxcnc", "machine": "millstone"}).json()
    assert obs["canonical"]["geometry"]["diameter"]["source"] == \
        "observed:linuxcnc@millstone"


@pytest.mark.contract
def test_assert_sets_nominal_fields_with_asserted_provenance(solo_client):
    """A catalog type's nominal spec is a deliberate assertion — there is no
    observe door, because a machine never measures a type. The assert door edits
    a seeded record (here, declaring a published diameter)."""
    rid = seed(solo_client)["internal"]["id"]
    solo_client.post(f"{BASE}/{rid}/assert",
                     json={"path": "geometry.diameter", "value": 6.35, "unit": "mm",
                           "actor": "catalog-import"})
    doc = conforms(solo_client.get(f"{BASE}/{rid}").json())     # round-trips via GET
    dia = doc["canonical"]["geometry"]["diameter"]
    assert dia["value"] == 6.35 and dia["source"] == "asserted:catalog-import"
