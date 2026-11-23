import json
import os

import logic


def test_only_ingress_gateway_and_loopback_allowed():
    assert logic.client_allowed("172.30.32.2")
    assert logic.client_allowed("127.0.0.1")
    assert logic.client_allowed("::1")
    assert logic.client_allowed("::ffff:172.30.32.2")
    assert not logic.client_allowed("172.30.32.1")  # HA Core
    assert not logic.client_allowed("172.30.33.5")  # another app
    assert not logic.client_allowed("::ffff:172.30.33.5")
    assert not logic.client_allowed("")


def test_csrf_header_required():
    assert logic.csrf_ok({"X-Requested-With": "browser-panel"})
    assert not logic.csrf_ok({})
    assert not logic.csrf_ok({"X-Requested-With": "XMLHttpRequest"})


def test_parse_targets_keeps_pages_only():
    raw = json.dumps([
        {"type": "page", "title": "Login", "url": "https://a/"},
        {"type": "service_worker", "title": "sw", "url": "https://a/sw.js"},
        {"type": "page", "url": "about:blank"},
        "junk",
    ])
    assert logic.parse_targets(raw) == [{"title": "Login", "url": "https://a/"}, {"title": "", "url": "about:blank"}]


def test_parse_targets_bad_json():
    assert logic.parse_targets("not json") == []


def test_status_reports_down_chromium():
    def refused():
        raise ConnectionRefusedError

    assert logic.status(refused) == {"chromium": False, "tabs": []}


def test_status_reports_tabs():
    assert logic.status(lambda: json.dumps([{"type": "page", "title": "T", "url": "u"}])) == {
        "chromium": True, "tabs": [{"title": "T", "url": "u"}]}


def test_wipe_profile_keeps_dir_and_does_not_follow_links(tmp_path):
    profile = tmp_path / "profile"
    (profile / "Default").mkdir(parents=True)
    (profile / "Default" / "Cookies").write_text("x")
    (profile / "Local State").write_text("{}")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    (profile / "link").symlink_to(outside)

    assert logic.wipe_profile(profile) == 3
    assert profile.is_dir() and list(profile.iterdir()) == []
    assert (outside / "keep.txt").exists()
    assert oct(os.stat(profile).st_mode & 0o777) == "0o700"


def test_wipe_missing_profile(tmp_path):
    assert logic.wipe_profile(tmp_path / "nope") == 0
