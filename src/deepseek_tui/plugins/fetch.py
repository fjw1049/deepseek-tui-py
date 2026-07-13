"""Explicit, read-only materialization of remote plugin source packages."""

from __future__ import annotations

import io
import re
import tarfile
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlparse

import httpx

from deepseek_tui.plugins.source import LocalArtifact

_GITHUB_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_GIT_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


class RemoteFetchError(ValueError):
    pass


class _RemoteMissing(RemoteFetchError):
    pass


@dataclass(frozen=True, slots=True)
class GitSubdirSource:
    owner: str
    repo: str
    subdir: str
    ref: str | None = None

    @classmethod
    def parse(
        cls,
        url: str,
        subdir: str,
        *,
        ref: str | None = None,
    ) -> GitSubdirSource:
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in {"github.com", "www.github.com"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
            or parsed.query
            or parsed.fragment
        ):
            raise RemoteFetchError("git-subdir URL must be a plain GitHub HTTPS URL")
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) != 2:
            raise RemoteFetchError("git-subdir URL must identify one GitHub repository")
        owner, repo = parts
        if repo.endswith(".git"):
            repo = repo[:-4]
        if not _GITHUB_NAME.fullmatch(owner) or not _GITHUB_NAME.fullmatch(repo):
            raise RemoteFetchError("invalid GitHub owner or repository name")
        normalized_subdir = _normalize_subdir(subdir)
        normalized_ref = _normalize_ref(ref)
        return cls(owner, repo, normalized_subdir, normalized_ref)

    @property
    def install_spec(self) -> str:
        base = f"github:{self.owner}/{self.repo}#{self.subdir}"
        if self.ref:
            return f"{base}@{self.ref}"
        return base

    def archive_candidates(self) -> tuple[tuple[str, str], ...]:
        if self.ref:
            refs: tuple[str, ...] = (self.ref,)
            # Explicit refs may be branch names or commit SHAs.
            urls = []
            for ref in refs:
                if _looks_like_commit(ref):
                    urls.append(
                        (
                            ref,
                            f"https://codeload.github.com/{self.owner}/{self.repo}/tar.gz/"
                            f"{quote(ref, safe='')}",
                        )
                    )
                else:
                    urls.append(
                        (
                            ref,
                            f"https://codeload.github.com/{self.owner}/{self.repo}/tar.gz/"
                            f"refs/heads/{quote(ref, safe='/')}",
                        )
                    )
                    urls.append(
                        (
                            ref,
                            f"https://codeload.github.com/{self.owner}/{self.repo}/tar.gz/"
                            f"refs/tags/{quote(ref, safe='/')}",
                        )
                    )
            return tuple(urls)
        refs = ("main", "master")
        return tuple(
            (
                ref,
                f"https://codeload.github.com/{self.owner}/{self.repo}/tar.gz/"
                f"refs/heads/{quote(ref, safe='/')}",
            )
            for ref in refs
        )


def _looks_like_commit(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{7,40}", value))


@dataclass(frozen=True, slots=True)
class NpmPackageSource:
    """Fetch a public npm package tarball (scripts disabled at install time)."""

    name: str
    version: str = "latest"

    @classmethod
    def parse(cls, spec: str) -> NpmPackageSource:
        raw = spec.strip()
        if raw.startswith("npm:"):
            raw = raw[4:]
        if not raw:
            raise RemoteFetchError("npm package name is required")
        if raw.startswith("@"):
            # @scope/name@version
            if raw.count("@") >= 2:
                name, version = raw.rsplit("@", 1)
            else:
                name, version = raw, "latest"
        elif "@" in raw:
            name, version = raw.rsplit("@", 1)
        else:
            name, version = raw, "latest"
        if ".." in name or "\\" in name or "\x00" in name:
            raise RemoteFetchError("invalid npm package name")
        if not re.fullmatch(r"(@[A-Za-z0-9~._-]+/)?[A-Za-z0-9~._-]+", name):
            raise RemoteFetchError("invalid npm package name")
        if not re.fullmatch(r"[A-Za-z0-9._+-]+", version):
            raise RemoteFetchError("invalid npm package version")
        return cls(name, version)

    @property
    def registry_url(self) -> str:
        return f"https://registry.npmjs.org/{quote(self.name, safe='@/')}"


@contextmanager
def materialize_npm_package(
    source: NpmPackageSource,
    *,
    max_files: int = 20_000,
    max_bytes: int = 20 * 1024 * 1024,
    temp_parent: Path | None = None,
) -> Iterator[ResolvedGitSubdir]:
    """Download one npm package tarball into a temporary artifact."""
    meta_url = source.registry_url
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        response = client.get(meta_url)
        if response.status_code == 404:
            raise RemoteFetchError(f"npm package not found: {source.name}")
        response.raise_for_status()
        document = response.json()
        if source.version == "latest":
            version = str(document.get("dist-tags", {}).get("latest") or "")
        else:
            version = source.version
        versions = document.get("versions") or {}
        if version not in versions:
            raise RemoteFetchError(f"npm version not found: {source.name}@{version}")
        dist = versions[version].get("dist") or {}
        tarball = dist.get("tarball")
        if not isinstance(tarball, str) or not tarball.startswith("https://"):
            raise RemoteFetchError("npm package is missing a https tarball URL")
        parsed = urlparse(tarball)
        if parsed.hostname not in {"registry.npmjs.org", "registry.npmmirror.com"}:
            raise RemoteFetchError("npm tarball host is not allowed")
        archive = client.get(tarball)
        archive.raise_for_status()
        data = archive.content
        if len(data) > max_bytes:
            raise RemoteFetchError(f"npm tarball exceeds {max_bytes} bytes")

    parent = str(temp_parent) if temp_parent is not None else None
    with tempfile.TemporaryDirectory(prefix="deepseek-npm-", dir=parent) as temp:
        extracted = Path(temp) / "pkg"
        _extract_archive(data, extracted, max_files=max_files, max_bytes=max_bytes)
        # npm tarballs usually contain a single top-level "package/" dir.
        package = extracted
        children = [p for p in extracted.iterdir() if p.is_dir()]
        if len(children) == 1 and (children[0] / "package.json").is_file():
            package = children[0]
        digest = LocalArtifact(package, max_files=max_files, max_bytes=max_bytes).digest
        yield ResolvedGitSubdir(package, version, tarball, digest)


@dataclass(frozen=True, slots=True)
class ResolvedGitSubdir:
    path: Path
    ref: str
    archive_url: str
    digest: str


def _normalize_subdir(value: str) -> str:
    if not value or "\\" in value or "\x00" in value:
        raise RemoteFetchError("invalid git-subdir path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise RemoteFetchError("git-subdir path must stay inside the repository")
    normalized = path.as_posix()
    return normalized or "."


def _normalize_ref(value: str | None) -> str | None:
    if value is None:
        return None
    ref = value.strip()
    if (
        not _GIT_REF.fullmatch(ref)
        or ".." in PurePosixPath(ref).parts
        or ref.endswith("/")
        or "//" in ref
    ):
        raise RemoteFetchError("invalid GitHub branch ref")
    return ref


def _download_archive(url: str, max_bytes: int) -> bytes:
    """Download directly from codeload without following redirects."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "codeload.github.com":
        raise RemoteFetchError("remote archive host is not allowed")
    payload = bytearray()
    with httpx.Client(timeout=30.0, follow_redirects=False) as client:
        with client.stream("GET", url) as response:
            if response.status_code == 404:
                raise _RemoteMissing(url)
            if response.is_redirect:
                raise RemoteFetchError("remote archive redirect was rejected")
            response.raise_for_status()
            for chunk in response.iter_bytes(chunk_size=64 * 1024):
                payload.extend(chunk)
                if len(payload) > max_bytes:
                    raise RemoteFetchError(
                        f"remote archive exceeds {max_bytes} compressed bytes"
                    )
    return bytes(payload)


def _common_prefix(members: list[tarfile.TarInfo]) -> str:
    prefixes = {PurePosixPath(member.name).parts[0] for member in members if member.name}
    return next(iter(prefixes)) if len(prefixes) == 1 else ""


def _strip_prefix(name: str, prefix: str) -> str:
    if not prefix:
        return name
    if name == prefix:
        return ""
    marker = f"{prefix}/"
    return name[len(marker) :] if name.startswith(marker) else name


def _extract_archive(
    data: bytes,
    destination: Path,
    *,
    max_files: int,
    max_bytes: int,
) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    try:
        archive = tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")
    except (tarfile.TarError, OSError) as exc:
        raise RemoteFetchError(f"invalid remote archive: {exc}") from exc
    with archive:
        members = archive.getmembers()
        if not members:
            raise RemoteFetchError("remote archive is empty")
        if len(members) > max_files:
            raise RemoteFetchError(f"remote archive contains more than {max_files} members")
        prefix = _common_prefix(members)
        expanded_bytes = 0
        for member in members:
            if not (member.isdir() or member.isfile()):
                raise RemoteFetchError(
                    f"remote archive contains a link or special file: {member.name}"
                )
            raw_path = PurePosixPath(member.name)
            if raw_path.is_absolute() or ".." in raw_path.parts or "\\" in member.name:
                raise RemoteFetchError(f"remote archive path is unsafe: {member.name}")
            relative = _strip_prefix(member.name, prefix)
            if not relative:
                continue
            target = (destination / relative).resolve(strict=False)
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise RemoteFetchError(
                    f"remote archive path escapes extraction root: {member.name}"
                ) from exc
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            expanded_bytes += int(member.size or 0)
            if expanded_bytes > max_bytes:
                raise RemoteFetchError(
                    f"remote archive exceeds {max_bytes} expanded bytes"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise RemoteFetchError(f"cannot read remote archive member: {member.name}")
            target.write_bytes(source.read())


@contextmanager
def materialize_git_subdir(
    source: GitSubdirSource,
    *,
    max_files: int = 20_000,
    max_bytes: int = 20 * 1024 * 1024,
    temp_parent: Path | None = None,
) -> Iterator[ResolvedGitSubdir]:
    """Fetch one explicit GitHub subdirectory into a temporary artifact."""
    data: bytes | None = None
    selected_ref = ""
    selected_url = ""
    errors: list[str] = []
    for ref, url in source.archive_candidates():
        try:
            data = _download_archive(url, max_bytes)
            selected_ref = ref
            selected_url = url
            break
        except _RemoteMissing:
            errors.append(f"{ref}: not found")
        except (httpx.HTTPError, RemoteFetchError) as exc:
            errors.append(f"{ref}: {exc}")
    if data is None:
        raise RemoteFetchError("remote download failed: " + "; ".join(errors))

    parent = str(temp_parent) if temp_parent is not None else None
    with tempfile.TemporaryDirectory(prefix="deepseek-plugin-", dir=parent) as temp:
        extracted = Path(temp) / "repo"
        try:
            _extract_archive(
                data,
                extracted,
                max_files=max_files,
                max_bytes=max_bytes,
            )
        except RemoteFetchError:
            raise
        except OSError as exc:
            raise RemoteFetchError(f"cannot extract remote archive: {exc}") from exc
        package = extracted if source.subdir == "." else (extracted / source.subdir)
        package = package.resolve()
        try:
            package.relative_to(extracted.resolve())
        except ValueError as exc:
            raise RemoteFetchError("git-subdir path escapes extracted repository") from exc
        if not package.is_dir():
            raise RemoteFetchError(f"git-subdir does not exist: {source.subdir}")
        try:
            digest = LocalArtifact(
                package,
                max_files=max_files,
                max_bytes=max_bytes,
            ).digest
        except ValueError as exc:
            raise RemoteFetchError(f"remote package validation failed: {exc}") from exc
        yield ResolvedGitSubdir(package, selected_ref, selected_url, digest)
