import json

import options


def test_defaults_when_file_missing(tmp_path):
    opts = options.load(tmp_path / "missing.json")
    assert opts["allowed_origins"] == [] and opts["blocked_origins"] == []


def test_upstream_argv_minimal():
    argv = options.upstream_argv({"allowed_origins": [], "blocked_origins": []})
    assert argv[0].endswith("@playwright/mcp/cli.js")
    assert "--cdp-endpoint" in argv and argv[argv.index("--cdp-endpoint") + 1] == "http://127.0.0.1:9222"
    assert argv[argv.index("--image-responses") + 1] == "omit"
    assert argv[argv.index("--codegen") + 1] == "none"
    assert argv[argv.index("--output-dir") + 1] == "/share/playwright"
    assert "--allowed-origins" not in argv and "--blocked-origins" not in argv
    assert "--port" not in argv


def test_upstream_argv_origins_joined_and_cleaned(tmp_path):
    path = tmp_path / "options.json"
    path.write_text(json.dumps({"allowed_origins": [" https://a.example ", "", "https://b.example"],
                                "blocked_origins": ["https://ads.example"]}))
    argv = options.upstream_argv(options.load(path))
    assert argv[argv.index("--allowed-origins") + 1] == "https://a.example;https://b.example"
    assert argv[argv.index("--blocked-origins") + 1] == "https://ads.example"


def test_child_env_strips_supervisor_token():
    env = options.child_env({"SUPERVISOR_TOKEN": "secret", "PATH": "/usr/bin", "HASSIO_TOKEN": "x"})
    assert "SUPERVISOR_TOKEN" not in env and "HASSIO_TOKEN" not in env
    assert env["PATH"] == "/usr/bin"
    assert env["PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD"] == "1"


def test_idle_reset_minutes(tmp_path):
    assert options.idle_reset_seconds(options.load(tmp_path / "missing.json")) == 300
    path = tmp_path / "options.json"
    path.write_text(json.dumps({"idle_reset_minutes": 0}))
    assert options.idle_reset_seconds(options.load(path)) is None
    path.write_text(json.dumps({"idle_reset_minutes": 10}))
    assert options.idle_reset_seconds(options.load(path)) == 600
