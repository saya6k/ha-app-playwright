import hashlib
import http.client
import io
import json

import install

FONT_A = b"font-a-bytes"
FONT_B = b"font-b-bytes"
MANIFEST = {"languages": {
    "ko": [{"file": "KR-Regular.otf", "url": "https://x/KR-Regular.otf", "sha256": hashlib.sha256(FONT_A).hexdigest()}],
    "ja": [{"file": "JP-Regular.otf", "url": "https://x/JP-Regular.otf", "sha256": hashlib.sha256(FONT_B).hexdigest()}],
}}
BODIES = {"https://x/KR-Regular.otf": FONT_A, "https://x/JP-Regular.otf": FONT_B}


class Fetcher:
    def __init__(self, bodies):
        self.bodies, self.urls = bodies, []

    def __call__(self, url):
        self.urls.append(url)
        if url not in self.bodies:
            raise OSError("unreachable")
        return io.BytesIO(self.bodies[url])


def test_selected_languages_from_options(tmp_path):
    opts = tmp_path / "options.json"
    opts.write_text(json.dumps({"font_languages": ["ko", "xx", "ko", "ja"]}))
    assert install.selected(opts, MANIFEST) == ["ko", "ja"]


def test_selected_missing_options(tmp_path):
    assert install.selected(tmp_path / "none.json", MANIFEST) == []


def test_installs_selected_language(tmp_path):
    fetch = Fetcher(BODIES)
    summary = install.install(["ko"], tmp_path, MANIFEST, fetch)
    assert (tmp_path / "KR-Regular.otf").read_bytes() == FONT_A
    assert not (tmp_path / "JP-Regular.otf").exists()
    assert summary == {"installed": ["KR-Regular.otf"], "kept": [], "removed": [], "failed": []}


def test_existing_verified_font_is_not_downloaded_again(tmp_path):
    (tmp_path / "KR-Regular.otf").write_bytes(FONT_A)
    fetch = Fetcher(BODIES)
    summary = install.install(["ko"], tmp_path, MANIFEST, fetch)
    assert fetch.urls == []
    assert summary["kept"] == ["KR-Regular.otf"]


def test_corrupt_existing_font_is_replaced(tmp_path):
    (tmp_path / "KR-Regular.otf").write_bytes(b"truncated")
    summary = install.install(["ko"], tmp_path, MANIFEST, Fetcher(BODIES))
    assert (tmp_path / "KR-Regular.otf").read_bytes() == FONT_A
    assert summary["installed"] == ["KR-Regular.otf"]


def test_checksum_mismatch_is_rejected_and_nothing_left_behind(tmp_path):
    summary = install.install(["ko"], tmp_path, MANIFEST, Fetcher({"https://x/KR-Regular.otf": b"evil"}))
    assert summary["failed"] == ["KR-Regular.otf"]
    assert list(tmp_path.iterdir()) == []


def test_download_failure_does_not_raise(tmp_path):
    summary = install.install(["ko", "ja"], tmp_path, MANIFEST, Fetcher({"https://x/JP-Regular.otf": FONT_B}))
    assert summary["failed"] == ["KR-Regular.otf"]
    assert summary["installed"] == ["JP-Regular.otf"]


def test_connection_dropped_mid_download_does_not_raise(tmp_path):
    class Dropped(io.BytesIO):
        def read(self, *_):
            raise http.client.IncompleteRead(b"partial")

    summary = install.install(["ko"], tmp_path, MANIFEST, lambda url: Dropped())
    assert summary["failed"] == ["KR-Regular.otf"]
    assert list(tmp_path.iterdir()) == []


def test_deselected_language_is_removed(tmp_path):
    (tmp_path / "KR-Regular.otf").write_bytes(FONT_A)
    (tmp_path / "JP-Regular.otf").write_bytes(FONT_B)
    summary = install.install(["ja"], tmp_path, MANIFEST, Fetcher(BODIES))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["JP-Regular.otf"]
    assert summary["removed"] == ["KR-Regular.otf"]


def test_creates_font_dir(tmp_path):
    target = tmp_path / "fonts"
    install.install([], target, MANIFEST, Fetcher(BODIES))
    assert target.is_dir()


def test_shipped_manifest_is_well_formed():
    manifest = install.load_manifest()
    assert set(manifest["languages"]) == {"ja", "ko", "zh-hans", "zh-hant"}
    for entries in manifest["languages"].values():
        for e in entries:
            assert e["url"].startswith("https://raw.githubusercontent.com/notofonts/noto-cjk/Sans2.004/")
            assert e["url"].endswith("/" + e["file"])
            assert len(e["sha256"]) == 64
