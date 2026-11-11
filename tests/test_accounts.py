"""Users and sign-in, through the HTTP seam.

- every /api route but the health check and the auth routes needs a session;
- a user can sign up with or without a password, sign in, and sign out;
- a password is stored only as an Argon2id hash — never in plain text, never
  in an API response — and session tokens only as digests;
- each user who signs up alone is a separate household: one user's data is
  invisible to another;
- an invite link signs a new user up into the inviter's household, or moves a
  signed-in user into it; the link expires, can be revoked, and its token is
  only stored as a digest;
- a household can be personalised (name, mark, accent colour), shared by all
  its members;
- the first user takes over the household that predates users;
- a password can be set, changed or removed, which needs the current one and
  signs the user's other devices out;
- only the owner's household (the first user and whoever they invite) may
  use the server's own model credentials.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from food_planer.clients import ConfiguredLLMClient


@pytest.fixture
def anon(make_client, data_dir: Path):
    """A client nobody is signed in on."""
    return make_client(data_dir, signed_in=False)


def signup(client, username: str, password: str | None = None):
    return client.post("/api/auth/signup", json={"username": username, "password": password})


def login(client, username: str, password: str | None = None):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def test_the_api_needs_a_session(anon):
    assert anon.get("/api/health").status_code == 200
    assert anon.get("/api/dishes").status_code == 401
    assert anon.get("/api/settings").status_code == 401
    assert anon.get("/api/auth/me").status_code == 401


def test_sign_up_without_a_password_and_sign_in_by_name(anon):
    created = signup(anon, "Ada")
    assert created.status_code == 201
    assert created.json()["hasPassword"] is False
    assert anon.get("/api/auth/me").json()["username"] == "Ada"

    assert anon.post("/api/auth/logout").status_code == 204
    assert anon.get("/api/dishes").status_code == 401

    assert login(anon, "ada").status_code == 200  # names are case-insensitive
    assert anon.get("/api/dishes").status_code == 200
    # A password typed for a user that has none is refused.
    anon.post("/api/auth/logout")
    assert login(anon, "Ada", "something").status_code == 401


def test_sign_in_with_a_password(anon):
    signup(anon, "Bo", "correct horse")
    anon.post("/api/auth/logout")

    for wrong in [None, "", "wrong password", "Correct horse"]:
        resp = login(anon, "Bo", wrong)
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Wrong username or password"
    # An unknown name gets the same answer as a wrong password.
    assert login(anon, "Nobody", "correct horse").json()["detail"] == "Wrong username or password"

    assert login(anon, "Bo", "correct horse").status_code == 200
    assert anon.get("/api/auth/me").json()["hasPassword"] is True


def test_the_password_is_only_stored_as_an_argon2id_hash(anon, data_dir: Path):
    body = signup(anon, "Bo", "correct horse").json()
    assert "correct horse" not in json.dumps(body)
    assert "passwordHash" not in body

    raw = (data_dir / "users.json").read_text("utf-8")
    assert "correct horse" not in raw
    stored = json.loads(raw)[0]["passwordHash"]
    assert stored.startswith("$argon2id$")

    token = anon.cookies.get("fp_session")
    assert token and token not in (data_dir / "sessions.json").read_text("utf-8")


def test_usernames_are_unique_and_passwords_long_enough(anon):
    signup(anon, "Ada")
    assert signup(anon, " ADA ").status_code == 422
    assert signup(anon, "Cy", "short").status_code == 422
    assert signup(anon, "x").status_code == 422
    assert signup(anon, "<script>").status_code == 422


def test_each_user_is_their_own_household(make_client, data_dir: Path):
    ada = make_client(data_dir, signed_in=False)
    signup(ada, "Ada")
    ada.post("/api/dishes", json={"title": "Lasagne"})

    bo = make_client(data_dir, signed_in=False)
    signup(bo, "Bo")
    assert bo.get("/api/dishes").json() == []
    bo.post("/api/dishes", json={"title": "Pho"})

    assert [d["title"] for d in ada.get("/api/dishes").json()] == ["Lasagne"]


def test_the_first_user_takes_over_the_existing_household(make_client, data_dir: Path):
    # A household from before there were users: its files at the top of data/.
    data_dir.mkdir(parents=True)
    dish = {"id": "d1", "title": "Frikadeller", "ingredients": None,
            "substitutes": None, "recipe": None, "favourite": False}
    (data_dir / "dishes.json").write_text(json.dumps([dish]), "utf-8")

    first = make_client(data_dir, signed_in=False)
    signup(first, "Ada")
    assert [d["title"] for d in first.get("/api/dishes").json()] == ["Frikadeller"]
    assert not (data_dir / "dishes.json").exists()
    assert first.get("/api/auth/me").json()["owner"] is True

    second = make_client(data_dir, signed_in=False)
    signup(second, "Bo")
    assert second.get("/api/dishes").json() == []
    assert second.get("/api/auth/me").json()["owner"] is False


def test_changing_the_password_needs_the_current_one(make_client, data_dir: Path):
    from fastapi.testclient import TestClient

    phone = make_client(data_dir, signed_in=False)
    signup(phone, "Bo", "correct horse")
    # A second device on the same server.
    laptop = TestClient(phone.app)
    login(laptop, "Bo", "correct horse")

    change = {"currentPassword": "wrong one", "newPassword": "battery staple"}
    assert phone.put("/api/auth/password", json=change).status_code == 403

    change["currentPassword"] = "correct horse"
    assert phone.put("/api/auth/password", json=change).status_code == 200
    # This device stays signed in; the others are signed out.
    assert phone.get("/api/dishes").status_code == 200
    assert laptop.get("/api/dishes").status_code == 401

    phone.post("/api/auth/logout")
    assert login(phone, "Bo", "correct horse").status_code == 401
    assert login(phone, "Bo", "battery staple").status_code == 200


def test_a_password_can_be_removed_and_added_later(anon):
    signup(anon, "Bo", "correct horse")
    removed = anon.put(
        "/api/auth/password", json={"currentPassword": "correct horse", "newPassword": None}
    )
    assert removed.json()["hasPassword"] is False
    anon.post("/api/auth/logout")
    assert login(anon, "Bo").status_code == 200

    # No current password needed when there is none.
    added = anon.put("/api/auth/password", json={"newPassword": "battery staple"})
    assert added.json()["hasPassword"] is True


def test_only_the_owners_household_may_use_the_servers_own_credentials(make_client, data_dir: Path):
    owner = make_client(data_dir, signed_in=False)
    signup(owner, "Ada")
    guest = make_client(data_dir, signed_in=False)
    signup(guest, "Bo")

    assert owner.get("/api/model").json()["usesOwnCredentialsOnly"] is False
    assert guest.get("/api/model").json()["usesOwnCredentialsOnly"] is True
    status = guest.get("/api/model/claude-status").json()
    assert status["loggedIn"] is False and status["needsToken"] is True

    for config in ({}, {"provider": "claude-code"}):
        with pytest.raises(PermissionError):
            ConfiguredLLMClient(lambda c=config: c, machine_credentials=False)._client()
    # With a key of their own, they can.
    own = {"openaiApiKey": "sk-mine"}
    assert ConfiguredLLMClient(lambda: own, machine_credentials=False)._client().api_key == "sk-mine"


def another(client):
    """A second device on the same running server: same app, own cookies."""
    from fastapi.testclient import TestClient

    return TestClient(client.app)


def invite(client) -> str:
    resp = client.post("/api/household/invites")
    assert resp.status_code == 201
    return resp.json()["token"]


def test_an_invite_link_signs_up_into_the_same_household(make_client, data_dir: Path):
    ada = make_client(data_dir, signed_in=False)
    signup(ada, "Ada")
    ada.post("/api/dishes", json={"title": "Lasagne"})
    token = invite(ada)

    bo = another(ada)
    # Before signing up, the link says whose household it is.
    preview = bo.get(f"/api/invites/{token}").json()
    assert preview["invitedBy"] == "Ada"
    assert preview["householdName"] == "Ada's household"

    resp = bo.post("/api/auth/signup", json={"username": "Bo", "invite": token})
    assert resp.status_code == 201
    assert resp.json()["householdId"] == ada.get("/api/auth/me").json()["householdId"]

    # Everything is shared, both ways.
    assert [d["title"] for d in bo.get("/api/dishes").json()] == ["Lasagne"]
    bo.post("/api/dishes", json={"title": "Pho"})
    assert {d["title"] for d in ada.get("/api/dishes").json()} == {"Lasagne", "Pho"}
    members = {m["username"] for m in ada.get("/api/household").json()["members"]}
    assert members == {"Ada", "Bo"}

    # A link works for more than one person while it lives.
    cy = another(ada)
    assert cy.post("/api/auth/signup", json={"username": "Cy", "invite": token}).status_code == 201
    assert len(cy.get("/api/dishes").json()) == 2


def test_the_invite_token_is_only_stored_as_a_digest(make_client, data_dir: Path):
    ada = make_client(data_dir, signed_in=False)
    signup(ada, "Ada")
    token = invite(ada)
    assert token not in (data_dir / "invites.json").read_text("utf-8")
    listed = ada.get("/api/household").json()["invites"]
    assert len(listed) == 1 and "token" not in listed[0]


def test_a_revoked_or_expired_or_made_up_invite_is_refused(make_client, data_dir: Path):
    ada = make_client(data_dir, signed_in=False)
    signup(ada, "Ada")
    token = invite(ada)
    invite_id = ada.get("/api/household").json()["invites"][0]["id"]
    assert ada.delete(f"/api/household/invites/{invite_id}").status_code == 204

    bo = another(ada)
    for bad in [token, "made-up", "æøå"]:
        assert bo.get(f"/api/invites/{bad}").status_code == 410
        resp = bo.post("/api/auth/signup", json={"username": "Bo", "invite": bad})
        assert resp.status_code == 410
    assert bo.get("/api/auth/me").status_code == 401

    # Expired: a week old.
    token = invite(ada)
    invites = json.loads((data_dir / "invites.json").read_text("utf-8"))
    for stored in invites.values():
        stored["expiresAt"] = "2000-01-01T00:00:00+00:00"
    (data_dir / "invites.json").write_text(json.dumps(invites), "utf-8")
    # A restarted app reads the expiry from disk.
    fresh = make_client(data_dir, signed_in=False)
    assert fresh.get(f"/api/invites/{token}").status_code == 410


def test_a_signed_in_user_can_join_through_an_invite(make_client, data_dir: Path):
    ada = make_client(data_dir, signed_in=False)
    signup(ada, "Ada")
    ada.post("/api/dishes", json={"title": "Lasagne"})

    bo = another(ada)
    signup(bo, "Bo")
    bo.post("/api/dishes", json={"title": "Pho"})

    token = invite(ada)
    assert ada.post("/api/household/join", json={"invite": token}).status_code == 409
    assert bo.post("/api/household/join", json={"invite": token}).status_code == 200
    assert [d["title"] for d in bo.get("/api/dishes").json()] == ["Lasagne"]
    # Membership is stored, so it survives a restart.
    again = make_client(data_dir, signed_in=False)
    login(again, "Bo")
    assert [d["title"] for d in again.get("/api/dishes").json()] == ["Lasagne"]


def test_the_household_appearance_is_shared_by_its_members(make_client, data_dir: Path):
    ada = make_client(data_dir, signed_in=False)
    signup(ada, "Ada")
    assert ada.get("/api/household/appearance").json() == {
        "name": None, "emoji": None, "accent": None,
    }
    saved = ada.put(
        "/api/household/appearance",
        json={"name": "  The Burrow ", "emoji": "🦔", "accent": "#2e7d6b"},
    )
    assert saved.json() == {"name": "The Burrow", "emoji": "🦔", "accent": "#2e7d6b"}
    assert ada.put("/api/household/appearance", json={"accent": "red"}).status_code == 422

    token = invite(ada)
    bo = another(ada)
    assert bo.get(f"/api/invites/{token}").json()["householdName"] == "The Burrow"
    bo.post("/api/auth/signup", json={"username": "Bo", "invite": token})
    assert bo.get("/api/household/appearance").json()["emoji"] == "🦔"

    # Blank goes back to the app's own.
    ada.put("/api/household/appearance", json={"name": " ", "emoji": "", "accent": None})
    assert bo.get("/api/household").json()["name"] == "Ada's household"


def test_the_owners_invitees_use_the_servers_own_credentials(make_client, data_dir: Path):
    ada = make_client(data_dir, signed_in=False)
    signup(ada, "Ada")  # the owner
    bo = another(ada)
    bo.post("/api/auth/signup", json={"username": "Bo", "invite": invite(ada)})
    assert bo.get("/api/model").json()["usesOwnCredentialsOnly"] is False

    # Someone in a household of their own still brings their own, and so does
    # whoever they invite.
    cy = another(ada)
    signup(cy, "Cy")
    dee = another(ada)
    dee.post("/api/auth/signup", json={"username": "Dee", "invite": invite(cy)})
    assert cy.get("/api/model").json()["usesOwnCredentialsOnly"] is True
    assert dee.get("/api/model").json()["usesOwnCredentialsOnly"] is True
