"""Users, sign-in sessions, households and invite links.

A user who signs up on their own starts a household of their own: its fridge,
dishes, My week, shopping list, settings and model keys live in
``data/users/<household id>/`` and no one outside it can see them. A household
is named after the user who started it, so its id is theirs. Anyone signing up
through an invite link joins the inviter's household instead and shares all
of it. What isn't anyone's — the imported recipes and the shop logos — stays
shared at the top of ``data/``.

A password is optional. When one is set it is stored only as an Argon2id hash
(salted, memory-hard, one-way): the app can check a password typed in, but no
one — not the person running the server, nor anyone reading ``data/`` — can
turn the hash back into the password. Without one, a user signs in with their
username alone, which is the trade-off they chose.

Sessions are random 256-bit tokens kept in an HttpOnly cookie; only their
SHA-256 digest is written to ``data/sessions.json``, so a copy of ``data/``
can't be used to sign in as anyone either. Invite tokens are kept the same
way, in ``data/invites.json``: a link can be shown once, when it's made.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from .store import ENTITY_DEFAULTS, JsonFile, Store, new_id

SESSION_COOKIE = "fp_session"
# A sign-in lasts a year on the device, like the app on a home screen should.
SESSION_MAX_AGE = 365 * 24 * 60 * 60
# An invite link works for a week, for as many people as it's sent to, until
# someone in the household revokes it.
INVITE_MAX_AGE = timedelta(days=7)

MIN_PASSWORD = 8
MAX_PASSWORD = 256
# Letters (æøå too), digits, spaces, dots, dashes and underscores.
USERNAME_RE = re.compile(r"^[\w .\-]{2,32}$")

# What the first user takes over from a single-household install: their data
# was at the top of data/ before there were users.
_HOUSEHOLD_DIRS = ("fridge_images", "run_logs")


class AccountError(ValueError):
    """A request the accounts can't satisfy; the message is safe to show."""


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _live(invite: dict) -> bool:
    return datetime.fromisoformat(invite["expiresAt"]) > _now()


def _key(username: str) -> str:
    return username.strip().casefold()


def household_of(user: dict) -> str:
    """The household a user belongs to. Users from before invites have no
    ``householdId``: each was the founder of their own."""
    return user.get("householdId") or user["id"]


def public_user(user: dict) -> dict:
    """What the API may say about a user: never the hash."""
    return {
        "id": user["id"],
        "username": user["username"],
        "hasPassword": bool(user.get("passwordHash")),
        "owner": bool(user.get("owner")),
        "householdId": household_of(user),
    }


def public_invite(invite: dict) -> dict:
    """An invite as the API lists it: never its token, which isn't kept."""
    return {k: invite[k] for k in ("id", "createdBy", "createdAt", "expiresAt")}


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Accounts:
    def __init__(
        self,
        root: str | Path,
        on_first_user: Callable[[Store], None] | None = None,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.users = JsonFile(self.root / "users.json", [])
        self.sessions = JsonFile(self.root / "sessions.json", {})
        self.invites = JsonFile(self.root / "invites.json", {})
        self._hasher = PasswordHasher()  # argon2id, RFC 9106 parameters
        # Verified against when a username doesn't exist, so a wrong username
        # takes as long to refuse as a wrong password.
        self._dummy_hash = self._hasher.hash(secrets.token_hex(16))
        self._stores: dict[str, Store] = {}
        self._on_first_user = on_first_user

    # --- Users ---------------------------------------------------------------

    def find(self, username: str) -> dict | None:
        key = _key(username)
        return next((u for u in self.users.read() if _key(u["username"]) == key), None)

    def get(self, user_id: str) -> dict | None:
        return next((u for u in self.users.read() if u["id"] == user_id), None)

    def _hash(self, password: str | None) -> str | None:
        if not password:
            return None
        if len(password) < MIN_PASSWORD:
            raise AccountError(f"A password needs at least {MIN_PASSWORD} characters")
        if len(password) > MAX_PASSWORD:
            raise AccountError("That password is too long")
        return self._hasher.hash(password)

    async def create(
        self, username: str, password: str | None, household_id: str | None = None
    ) -> dict:
        """A new user: in ``household_id`` when they came through an invite,
        otherwise the founder of a household of their own."""
        username = " ".join(username.split())
        if not USERNAME_RE.match(username):
            raise AccountError(
                "A username is 2–32 letters, digits, spaces, dots, dashes or underscores"
            )
        password_hash = self._hash(password)  # hashed outside the lock: it's slow

        def add(users: list) -> tuple[dict, bool]:
            if any(_key(u["username"]) == _key(username) for u in users):
                raise AccountError("That username is taken")
            user = {
                "id": new_id(),
                "username": username,
                "passwordHash": password_hash,
                # The first user runs the server: only they may fall back on
                # its own OpenAI key and Claude Code login (see the LLM client).
                "owner": not users,
                "createdAt": _now().isoformat(),
            }
            if household_id:
                user["householdId"] = household_id
            users.append(user)
            return user, user["owner"]

        user, first = await self.users.update(add)
        if first:
            self._adopt_single_household(user["id"])
        return user

    def verify(self, user: dict | None, password: str | None) -> bool:
        """Whether ``password`` signs ``user`` in. A user without a password
        signs in with none; typing one for them is refused, in case it was
        meant for a different account."""
        if user is None:
            try:
                self._hasher.verify(self._dummy_hash, password or "-")
            except VerificationError:
                pass
            return False
        stored = user.get("passwordHash")
        if not stored:
            return not password
        if not password:
            return False
        try:
            return self._hasher.verify(stored, password)
        except (VerificationError, InvalidHashError):
            return False

    async def set_password(self, user_id: str, password: str | None) -> dict:
        """Set, change or (with None) remove a user's password."""
        password_hash = self._hash(password)

        def change(users: list) -> dict:
            for user in users:
                if user["id"] == user_id:
                    user["passwordHash"] = password_hash
                    return user
            raise AccountError("No such user")

        return await self.users.update(change)

    def members(self, household_id: str) -> list[dict]:
        return [u for u in self.users.read() if household_of(u) == household_id]

    def uses_server_credentials(self, user: dict) -> bool:
        """Whether ``user`` may fall back on the server's own OpenAI key and
        Claude Code login: anyone in the owner's household. A user who started
        a household of their own brings their own key or token."""
        return any(u.get("owner") for u in self.members(household_of(user)))

    async def join(self, user_id: str, household_id: str) -> dict:
        """Move a user into another household. What their old one holds stays
        on disk (and with anyone else still in it), but they no longer see it."""

        def move(users: list) -> dict:
            for user in users:
                if user["id"] == user_id:
                    user["householdId"] = household_id
                    return user
            raise AccountError("No such user")

        return await self.users.update(move)

    # --- Invites -------------------------------------------------------------

    async def create_invite(self, user: dict) -> tuple[str, dict]:
        """A new invite link into ``user``'s household: the token (shown this
        once) and the invite as stored."""
        token = secrets.token_urlsafe(24)
        now = _now()
        invite = {
            "id": new_id(),
            "householdId": household_of(user),
            "createdBy": user["username"],
            "createdAt": now.isoformat(),
            "expiresAt": (now + INVITE_MAX_AGE).isoformat(),
        }

        def add(invites: dict) -> None:
            # Drop expired invites while we're here, so the file stays small.
            for digest in [d for d, i in invites.items() if not _live(i)]:
                del invites[digest]
            invites[_digest(token)] = invite

        await self.invites.update(add)
        return token, invite

    def invite_for(self, token: str | None) -> dict | None:
        """The live invite behind a token, or None if it's unknown, expired
        or revoked."""
        if not token:
            return None
        try:
            invite = self.invites.read().get(_digest(token))
        except UnicodeEncodeError:
            return None
        return invite if invite and _live(invite) else None

    def invites_of(self, household_id: str) -> list[dict]:
        return sorted(
            (i for i in self.invites.read().values()
             if i["householdId"] == household_id and _live(i)),
            key=lambda i: i["createdAt"],
        )

    async def revoke_invite(self, household_id: str, invite_id: str) -> None:
        def remove(invites: dict) -> None:
            for digest, invite in list(invites.items()):
                if invite["id"] == invite_id and invite["householdId"] == household_id:
                    del invites[digest]
                    return
            raise AccountError("No such invite")

        await self.invites.update(remove)

    # --- Sessions ------------------------------------------------------------

    async def start_session(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)

        def add(sessions: dict) -> None:
            sessions[_digest(token)] = {
                "userId": user_id,
                "createdAt": _now().isoformat(),
            }

        await self.sessions.update(add)
        return token

    def user_for(self, token: str | None) -> dict | None:
        if not token:
            return None
        session = self.sessions.read().get(_digest(token))
        return self.get(session["userId"]) if session else None

    async def end_session(self, token: str | None) -> None:
        if not token:
            return
        await self.sessions.update(lambda sessions: sessions.pop(_digest(token), None))

    async def end_other_sessions(self, user_id: str, keep: str | None) -> None:
        """Sign a user out everywhere but here — after a password change."""
        kept = _digest(keep) if keep else None

        def prune(sessions: dict) -> None:
            for digest in [d for d, s in sessions.items() if s["userId"] == user_id]:
                if digest != kept:
                    del sessions[digest]

        await self.sessions.update(prune)

    # --- Each household's data ----------------------------------------------

    def store_for(self, user: dict) -> Store:
        """The data of the household ``user`` belongs to — one Store per
        household, shared by everyone in it, so their writes share its locks."""
        household_id = household_of(user)
        store = self._stores.get(household_id)
        if store is None:
            store = Store(self.root / "users" / household_id, shared_dir=self.root)
            self._stores[household_id] = store
        return store

    def _adopt_single_household(self, user_id: str) -> None:
        """The first user takes over the household that was at the top of
        data/ before there were users: its JSON files, fridge photos and run
        logs move into their own directory. Shared data stays put."""
        home = self.root / "users" / user_id
        home.mkdir(parents=True, exist_ok=True)
        names: list[str] = [f"{name}.json" for name in ENTITY_DEFAULTS]
        names += list(_HOUSEHOLD_DIRS)
        for name in names:
            source = self.root / name
            if source.exists():
                shutil.move(str(source), str(home / name))
        store = self.store_for({"id": user_id})
        if self._on_first_user:
            self._on_first_user(store)
