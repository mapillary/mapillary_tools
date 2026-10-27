# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import py.path
import pytest
from mapillary_tools import config, exceptions

from .fixtures import (
    pytest_skip_if_not_ffmpeg_installed,
    run_command,
    run_process_and_upload_for_descs,
    run_process_for_descs,
    run_upload,
    setup_config,
    setup_data,
    setup_upload,
    USERNAME,
)


ORGANIZATION_ID = "1234567890"
ORGANIZATION_NAME = "Acme Mapping"


@pytest.fixture
def graph_api(monkeypatch: pytest.MonkeyPatch):
    """
    Serve the organization lookups of the Graph API locally,
    and return the organization IDs looked up
    """
    looked_up: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            organization_id = urlparse(self.path).path.strip("/")
            looked_up.append(organization_id)
            if organization_id == ORGANIZATION_ID:
                status = 200
                body = {"id": ORGANIZATION_ID, "name": ORGANIZATION_NAME}
            else:
                status = 400
                body = {"error": {"message": "Unsupported get request", "code": 100}}
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv(
        "MAPILLARY_GRAPH_API_ENDPOINT", f"http://127.0.0.1:{server.server_port}"
    )
    yield looked_up
    server.shutdown()
    server.server_close()
    thread.join()


def _history_organization_keys() -> list:
    history_path = Path(os.environ["MAPILLARY_UPLOAD_HISTORY_PATH"])
    return [
        json.loads(p.read_text())["params"]["organization_key"]
        for p in history_path.glob("*/*.json")
    ]


def _clear_history() -> None:
    shutil.rmtree(os.environ["MAPILLARY_UPLOAD_HISTORY_PATH"], ignore_errors=True)


def _saved_organizations(config_path: py.path.local) -> dict[str, str]:
    user_items = config.load_user(USERNAME, config_path=str(config_path))
    assert user_items is not None
    return config.list_organizations(user_items)


def test_save_then_use_organization_name(
    setup_config: py.path.local,
    setup_data: py.path.local,
    setup_upload: py.path.local,
    graph_api: list[str],
):
    images = str(setup_data.join("images"))

    # Save, and upload
    run_process_and_upload_for_descs(
        [
            "--file_types=image",
            *["--organization_key", ORGANIZATION_ID],
            *["--organization_name", "work"],
            images,
        ]
    )
    assert _saved_organizations(setup_config) == {"work": ORGANIZATION_ID}
    assert "MAPOrganizationKey" not in setup_config.read()
    keys = _history_organization_keys()
    assert keys and set(keys) == {ORGANIZATION_ID}
    assert graph_api == [ORGANIZATION_ID]

    # Use
    _clear_history()
    descs = run_process_for_descs(["--file_types=image", images])
    desc_path = setup_data.join("descs.json")
    desc_path.write(json.dumps(descs))
    run_upload([images, "--desc_path", str(desc_path), "--organization_name", "work"])
    keys = _history_organization_keys()
    assert keys and set(keys) == {ORGANIZATION_ID}
    assert graph_api == [ORGANIZATION_ID, ORGANIZATION_ID]


def test_video_process_and_upload_by_organization_name(
    setup_config: py.path.local,
    setup_data: py.path.local,
    setup_upload: py.path.local,
    graph_api: list[str],
):
    pytest_skip_if_not_ffmpeg_installed()
    config.save_organization(
        USERNAME, "work", ORGANIZATION_ID, config_path=str(setup_config)
    )

    run_command(
        [
            "--dry_run",
            *["--user_name", USERNAME],
            *["--organization_name", "work"],
            *["--video_sample_interval=2", "--video_sample_distance=-1"],
            str(setup_data.join("gopro_data").join("max-360mode.mp4")),
            str(setup_data.join("samples")),
        ],
        command="video_process_and_upload",
    )

    keys = _history_organization_keys()
    assert keys and set(keys) == {ORGANIZATION_ID}
    assert graph_api == [ORGANIZATION_ID]


def test_unknown_organization_name(
    setup_config: py.path.local,
    setup_data: py.path.local,
    setup_upload: py.path.local,
    graph_api: list[str],
):
    config.save_organization(
        USERNAME, "work", ORGANIZATION_ID, config_path=str(setup_config)
    )

    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        run_upload(
            [str(setup_data.join("images")), "--organization_name", "home"],
            capture_output=True,
            text=True,
        )

    assert excinfo.value.returncode == exceptions.MapillaryBadParameterError.exit_code
    stderr = excinfo.value.stderr
    assert f'Organization "home" not found in profile "{USERNAME}"' in stderr
    assert "--organization_key ID --organization_name home" in stderr
    assert "work" in stderr and ORGANIZATION_ID in stderr
    assert graph_api == []
    assert not os.listdir(setup_upload)


def test_organization_key_alone_saves_nothing(
    setup_config: py.path.local,
    setup_data: py.path.local,
    setup_upload: py.path.local,
    graph_api: list[str],
):
    before = setup_config.read_binary()

    run_process_and_upload_for_descs(
        [
            "--file_types=image",
            *["--organization_key", ORGANIZATION_ID],
            str(setup_data.join("images")),
        ]
    )

    assert setup_config.read_binary() == before
    keys = _history_organization_keys()
    assert keys and set(keys) == {ORGANIZATION_ID}
    assert graph_api == [ORGANIZATION_ID]


def test_organization_key_takes_only_an_id(
    setup_config: py.path.local,
    setup_data: py.path.local,
    setup_upload: py.path.local,
    graph_api: list[str],
):
    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        run_upload(
            [str(setup_data.join("images")), "--organization_key", "work"],
            capture_output=True,
            text=True,
        )

    assert "takes an organization ID" in excinfo.value.stderr
    assert graph_api == []
    assert not os.listdir(setup_upload)


def test_authenticate_lists_and_deletes_organization_names(
    setup_config: py.path.local,
):
    config.save_organization(
        USERNAME, "work", ORGANIZATION_ID, config_path=str(setup_config)
    )
    config.save_organization(
        USERNAME, "home", "2222222222", config_path=str(setup_config)
    )

    # Listed under the profile; a new token keeps them
    result = run_command(
        ["--user_name", USERNAME, "--jwt", "new_token"],
        command="authenticate",
        capture_output=True,
        text=True,
    )
    assert "organization work" in result.stderr
    assert "organization home" in result.stderr
    assert _saved_organizations(setup_config) == {
        "work": ORGANIZATION_ID,
        "home": "2222222222",
    }

    # Deletes only the name, without logging in
    run_command(
        [
            *["--user_name", USERNAME],
            *["--organization_name", "work"],
            "--delete",
        ],
        command="authenticate",
    )
    assert config.load_user(USERNAME, config_path=str(setup_config)) == {
        "user_upload_token": "new_token",
        "MAPOrganization.home": "2222222222",
    }
