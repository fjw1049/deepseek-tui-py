"""App-owned cookie persistence and opt-in, per-site, one-way Chrome synchronization."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken

from deepseek_tui.browser.chrome_cookies import profiles
from deepseek_tui.browser.sites import site_of
from deepseek_tui.utils import write_text_atomic
from deepseek_tui.workspace.project_lease import FileLease


def cookie_key(cookie: dict) -> str:
    return json.dumps(
        [cookie["domain"], cookie.get("path", "/"), cookie["name"], cookie.get("partitionKey")],
        sort_keys=True,
    )


def cookie_params(cookie: dict) -> dict:
    result = {
        key: value
        for key, value in cookie.items()
        if key
        in {
            "name",
            "value",
            "domain",
            "path",
            "secure",
            "httpOnly",
            "sameSite",
            "expires",
            "priority",
            "sourceScheme",
            "sourcePort",
            "partitionKey",
        }
    }
    if result.get("expires", -1) <= 0:
        result.pop("expires", None)
    if not result["domain"].startswith("."):
        domain = result.pop("domain")
        result["url"] = (
            ("https" if result.get("secure") else "http") + "://" + domain + result.get("path", "/")
        )
    return result


async def set_cookies(client, cookies: list[dict]) -> int:
    """Apply cookies and return how many Chrome rejected.

    One cookie with invalid fields makes Chrome reject the whole batch, so split it.
    """
    if not cookies:
        return 0
    try:
        await client.send("Network.setCookies", {"cookies": cookies})
        return 0
    except Exception as exc:
        if "Invalid cookie fields" not in str(exc):
            raise
        if len(cookies) == 1:
            return 1
    middle = len(cookies) // 2
    return await set_cookies(client, cookies[:middle]) + await set_cookies(client, cookies[middle:])


class CookieStore:
    def __init__(self, root: Path):
        self.root = root
        self.lock = asyncio.Lock()
        self.source_lock = asyncio.Lock()
        saved = self.settings()
        self.status = saved.get("status", "idle")
        self.count = saved.get("count", 0)
        self.skipped = saved.get("skipped", 0)
        self.domains = saved.get("domains", 0)
        # Background saves report separately so one transient failure does not stick.
        self.save_error = False

    def settings(self) -> dict:
        try:
            return json.loads((self.root / "sync.json").read_text())
        except (FileNotFoundError, ValueError):
            return {"consent": "pending", "profile": None}

    def state(self) -> dict:
        return {
            **self.settings(),
            "status": "save_failed" if self.save_error else self.status,
            "count": self.count,
            "skipped": self.skipped,
            "domains": self.domains,
        }

    def has_saved_cookies(self) -> bool:
        try:
            return any(
                c.get("expires", -1) <= 0 or c["expires"] > time.time()
                for c in self._read()["cookies"].values()
            )
        except (InvalidToken, ValueError, OSError):
            return False

    def configure(self, consent: str, profile: str | None) -> None:
        if consent == "enabled" and profile not in {p["id"] for p in profiles()}:
            raise ValueError("Choose an available Chrome profile")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        write_text_atomic(
            self.root / "sync.json", json.dumps({"consent": consent, "profile": profile})
        )
        self.status = "idle"
        self.count = self.skipped = self.domains = 0
        self.save_error = False

    async def clear(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        async with self.lock:
            async with FileLease(self.root / "cookies.lock"):
                try:
                    data = self._read()
                except (InvalidToken, ValueError, OSError):
                    # Explicit clear must also recover an unreadable local vault.
                    data = {"sites": []}
                    self.configure("disabled", None)
                    (self.root / "cookies.key").unlink(missing_ok=True)
                data.update(cookies={}, skip_legacy=True, native_pending=False,
                            native_migrated=True, native_removed=[])
                # Keep visited sites so clearing cannot silently import old logins.
                self._write(data)
        self.status, self.count, self.skipped, self.domains = "cleared", 0, 0, 0
        self.save_error = False
        write_text_atomic(self.root / "sync.json", json.dumps(self.state()))

    def _read(self) -> dict:
        path = self.root / "cookies.enc"
        if not path.exists():
            return {"cookies": {}, "sites": []}
        key = (self.root / "cookies.key").read_bytes()
        return json.loads(Fernet(key).decrypt(path.read_bytes()))

    def _write(self, data: dict) -> None:
        key_path = self.root / "cookies.key"
        if not key_path.exists():
            write_text_atomic(key_path, Fernet.generate_key().decode())
        encrypted = Fernet(key_path.read_bytes()).encrypt(json.dumps(data).encode())
        write_text_atomic(self.root / "cookies.enc", encrypted.decode())

    async def _edit(self, change) -> dict:
        async with self.lock:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            async with FileLease(self.root / "cookies.lock"):
                data = self._read()
                changed = change(data)
                now = time.time()
                expired = [
                    key for key, cookie in data["cookies"].items()
                    if 0 < cookie.get("expires", -1) <= now
                ]
                for key in expired:
                    del data["cookies"][key]
                if changed or expired:
                    self._write(data)
                return data

    async def restore(self, run) -> None:
        client = run.session._internal.client
        native = (await client.send("Storage.getCookies"))["cookies"]
        marker = run.profiles.get_or_create("workbench").data_dir / ".deepseek-shared-cookies"

        def migrate(data):
            if marker.exists() or data.get("skip_legacy"):
                return False
            for cookie in native:
                # Existing app logins take precedence over a first Chrome import.
                data["cookies"].setdefault(cookie_key(cookie), cookie)
                host = cookie["domain"].lstrip(".")
                if host not in data["sites"]:
                    data["sites"].append(host)
            return bool(native)

        data = await self._edit(migrate)
        await client.send("Network.clearBrowserCookies")
        cookies = [
            cookie_params(c)
            for c in data["cookies"].values()
            if not c.get("partitionKeyOpaque")
            and (c.get("expires", -1) <= 0 or c["expires"] > time.time())
        ]
        await set_cookies(client, cookies)
        write_text_atomic(marker, "1")
        run.cookie_baseline = {
            cookie_key(c): c for c in (await client.send("Storage.getCookies"))["cookies"]
        }

    async def apply_native(self, run) -> None:
        """Bring saved logins into Workbench's own browser without replacing its own:
        once for logins from the private browser, and after each Chrome sync made while
        it was not attached."""
        data = self._read()
        migrate = not data.get("native_migrated")
        pending = bool(data.get("native_pending")) and self.settings()["consent"] == "enabled"
        gone = data.get("native_removed") or []
        if not (migrate or pending or gone):
            return
        client = run.session._internal.client
        for cookie in gone:
            await client.send("Network.deleteCookies", cookie)
        present = {cookie_key(c) for c in (await client.send("Network.getAllCookies"))["cookies"]}
        chrome = set(data.get("chrome_sites", []))
        now = time.time()
        await set_cookies(client, [
            cookie_params(cookie) for key, cookie in data["cookies"].items()
            if not cookie.get("partitionKeyOpaque")
            and (cookie.get("expires", -1) <= 0 or cookie["expires"] > now)
            and ((pending and site_of(cookie["domain"]) in chrome)
                 or (migrate and key not in present))
        ])

        def done(data):
            data.update(native_migrated=True, native_pending=False, native_removed=[])
            return True

        await self._edit(done)

    async def capture(self, run) -> None:
        if run.cookie_baseline is None:
            return
        current = {
            cookie_key(c): c
            for c in (await run.session._internal.client.send("Storage.getCookies"))["cookies"]
        }
        previous = run.cookie_baseline
        if current == previous:
            return
        host = urlsplit(run.url).hostname

        def merge(data):
            changed = False
            for key in previous.keys() - current.keys():
                # A stale tab must not delete a newer cookie from another chat.
                if data["cookies"].get(key) == previous[key]:
                    data["cookies"].pop(key, None)
                    changed = True
            sites = set(data["sites"])
            for key, cookie in current.items():
                if previous.get(key) != cookie:
                    data["cookies"][key] = cookie
                    changed = True
                domain = cookie["domain"].lstrip(".")
                if domain not in sites:
                    sites.add(domain)
                    data["sites"].append(domain)
                    changed = True
            if host and host not in sites:
                data["sites"].append(host)
                changed = True
            return changed

        await self._edit(merge)
        run.cookie_baseline = current

    def selected_sites(self) -> list[str]:
        """Sites whose cookies mirror Chrome; every other site's cookies belong to the app."""
        try:
            return self._read().get("chrome_sites", [])
        except (InvalidToken, ValueError, OSError):
            return []

    async def _worker(self, *args: str, payload: dict | None = None) -> dict:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "deepseek_tui.browser.chrome_cookies",
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=os.name != "nt",
        )
        try:
            output, _ = await asyncio.wait_for(
                process.communicate(json.dumps(payload or {}).encode()), timeout=15
            )
            return json.loads(output) if process.returncode == 0 else {"error": "unavailable"}
        finally:
            if process.returncode is None:
                try:
                    if os.name == "nt":
                        process.kill()
                    else:
                        os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await process.communicate()

    async def list_source(self, profile: str) -> dict:
        return await self._worker("list", profile)

    async def read_source(self, profile: str, sites: list[str]) -> dict:
        return await self._worker("read", profile, payload={"sites": sites})

    async def sync(self, run=None, sites: list[str] | None = None) -> None:
        """Mirror the selected sites from Chrome; ``sites`` replaces the saved selection."""
        async with self.source_lock:
            settings = self.settings()
            if settings["consent"] != "enabled":
                return
            self.status = "syncing"
            self.count = self.skipped = self.domains = 0
            try:
                # Capture app changes before an explicit import overwrites matching cookies.
                if run:
                    await self.capture(run)
                previous = set(self._read().get("chrome_sites", []))
                selected = previous if sites is None else {site_of(site) for site in sites}
                result = (
                    await self.read_source(settings["profile"], sorted(selected))
                    if selected else {"cookies": [], "skipped": 0}
                )
                if self.settings() != settings:
                    self.status = "idle"
                    return
                if result.get("error") == "permission":
                    self.status = "permission_denied"
                    return
                if result.get("error"):
                    raise RuntimeError("Cookie source unavailable")
                cookies = []
                for source in result["cookies"]:
                    cookie = dict(source)
                    if "url" in cookie:
                        cookie["domain"] = urlsplit(cookie.pop("url")).hostname
                    cookie.setdefault("expires", -1)
                    if site_of(cookie["domain"]) in selected and (
                        cookie["expires"] <= 0 or cookie["expires"] > time.time()
                    ):
                        cookies.append(cookie)
            except Exception:
                self.status = "unavailable"
                return
            imported = {cookie_key(cookie) for cookie in cookies}
            removed = []

            def merge(data):
                # A successful empty read means sign-out; failed reads returned above.
                managed = set(data.get("chrome_sites", [])) | selected
                if result.get("skipped"):
                    # Partial decryption cannot prove missing cookies were removed.
                    managed -= selected
                for key, cookie in list(data["cookies"].items()):
                    if site_of(cookie["domain"]) in managed:
                        del data["cookies"][key]
                        if key not in imported:
                            removed.append(cookie)
                for cookie in cookies:
                    data["cookies"][cookie_key(cookie)] = cookie
                data["chrome_sites"] = sorted(selected)
                # Workbench's own browser picks these up when it next attaches.
                data["native_pending"] = not getattr(run, "native", False)
                if data["native_pending"]:
                    gone = data.setdefault("native_removed", [])
                    fields = ("name", "domain", "path", "partitionKey")
                    gone.extend({key: cookie[key] for key in fields if key in cookie}
                                for cookie in removed)
                    del gone[:-2000]
                return True

            try:
                # Save first, including when there is no browser session yet.
                await self._edit(merge)
            except Exception:
                self.status = "save_failed"
                return
            self.count = len(cookies)
            self.domains = len({site_of(cookie["domain"]) for cookie in cookies})
            self.skipped = result.get("skipped", 0)
            self.status = "partial" if self.skipped else "synced" if cookies else "empty"
            try:
                if run:
                    client = run.session._internal.client
                    for cookie in removed:
                        await client.send("Network.deleteCookies", {
                            key: cookie[key]
                            for key in ("name", "domain", "path", "partitionKey") if key in cookie
                        })
                    rejected = await set_cookies(client, [cookie_params(c) for c in cookies])
                    if rejected:
                        self.skipped += rejected
                        self.status = "partial"
                    await self.capture(run)
            except Exception:
                self.status = "apply_failed"
            try:
                write_text_atomic(
                    self.root / "sync.json", json.dumps({**self.state(), "status": self.status})
                )
            except OSError:
                self.status = "save_failed"
