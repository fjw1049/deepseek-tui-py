"""Regression coverage for malformed URLs and valid archive layouts."""

import io
import tarfile

import pytest

from deepseek_tui.automation.inbox import _parse_wecom_webhook_key
from deepseek_tui.browser.permissions import origin_of
from deepseek_tui.plugins.fetch import _extract_archive

KEY = "12345678-1234-1234-1234-123456789abc"


@pytest.mark.parametrize(
    "url, expected",
    [
        ("http://[::1]:8080/page", "http://[::1]:8080"),
        ("https://[2001:db8::1]/page", "https://[2001:db8::1]"),
    ],
)
def test_browser_origin_preserves_ipv6_authority(url, expected):
    assert origin_of(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "http",
        "https:///cgi-bin/webhook/send?key=" + KEY,
        "https://[invalid/cgi-bin/webhook/send?key=" + KEY,
        "https://qyapi.weixin.qq.com.evil.example/cgi-bin/webhook/send?key=" + KEY,
        "https://evilqyapi.weixin.qq.com/cgi-bin/webhook/send?key=" + KEY,
    ],
)
def test_wecom_rejects_malformed_or_foreign_urls(url):
    assert _parse_wecom_webhook_key(url) is None


def test_wecom_accepts_key_and_official_url():
    assert _parse_wecom_webhook_key(KEY) == KEY
    assert (
        _parse_wecom_webhook_key("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=" + KEY)
        == KEY
    )


@pytest.mark.parametrize("layout", ["dot_root", "single_file", "wrapper", "dot_wrapper"])
def test_archive_preserves_root_file(tmp_path, layout):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        if layout == "dot_root":
            root = tarfile.TarInfo(".")
            root.type = tarfile.DIRTYPE
            archive.addfile(root)
        name = {
            "dot_root": "./package.json",
            "single_file": "package.json",
            "wrapper": "package/package.json",
            "dot_wrapper": "./package/package.json",
        }[layout]
        member = tarfile.TarInfo(name)
        member.size = 2
        archive.addfile(member, io.BytesIO(b"{}"))
    _extract_archive(buffer.getvalue(), tmp_path, max_files=10, max_bytes=100)
    assert (tmp_path / "package.json").read_bytes() == b"{}"
