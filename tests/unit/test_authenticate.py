# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import json
import logging
import shutil
import sys
import typing as T
from pathlib import Path

import pytest
import requests
from mapillary_tools import api_v4, authenticate, config, constants, exceptions
from mapillary_tools.commands import __main__ as commands
from mapillary_tools.commands.process import Command as ProcessCommand
from mapillary_tools.commands.video_process import Command as VideoProcessCommand
from mapillary_tools.serializer.description import DescriptionJSONSerializer


ORGANIZATIONS = {"1234567890": "Acme Mapping", "2222222222": "Other Org"}
TEST_IMAGE_DIR = Path(__file__).parent.parent.joinpath("data", "images")


@pytest.fixture
def config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path.joinpath("configs", "CLIENT_ID")
    monkeypatch.setattr(config, "MAPILLARY_CONFIG_PATH", str(path))
    monkeypatch.setattr(constants, "PROMPT_DISABLED", True)
    monkeypatch.setattr(constants, "_AUTH_VERIFICATION_DISABLED", True)
    return path


@pytest.fixture
def fetched(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """
    Mock api_v4.fetch_organization, and return the organization IDs it fetches
    """
    fetched_ids: list[str] = []

    def _fetch_organization(
        user_session: requests.Session, organization_id: int | str
    ) -> requests.Response:
        fetched_ids.append(str(organization_id))
        resp = requests.Response()
        server_id = str(organization_id).lstrip("0")
        if server_id in ORGANIZATIONS:
            resp.status_code = 200
            resp._content = json.dumps(
                {"id": server_id, "name": ORGANIZATIONS[server_id]}
            ).encode()
        else:
            resp.status_code = 400
            resp._content = b'{"error": {"message": "Unsupported get request"}}'
        resp.raise_for_status()
        return resp

    monkeypatch.setattr(api_v4, "fetch_organization", _fetch_organization)
    return fetched_ids


def _add_profile(name: str, **items: str) -> None:
    config.update_config(
        name, T.cast(config.UserItem, {"user_upload_token": f"{name}_token", **items})
    )


def _saved(profile_name: str) -> dict[str, str]:
    user_items = config.load_user(profile_name)
    assert user_items is not None
    return config.list_organizations(user_items)


def _enable_prompt(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> None:
    monkeypatch.setattr(authenticate, "_prompt_enabled", lambda: True)
    monkeypatch.setattr(authenticate, "_prompt", lambda message: answers.pop(0))


def test_save_then_use_organization_name(
    config_path: Path, fetched: list[str], caplog: pytest.LogCaptureFixture
):
    _add_profile("me")
    caplog.set_level(logging.INFO)

    user_items = authenticate.fetch_user_items(
        user_name="me", organization_key="1234567890", organization_name="work"
    )
    assert user_items["MAPOrganizationKey"] == "1234567890"
    assert fetched == ["1234567890"]
    assert _saved("me") == {"work": "1234567890"}
    assert (
        'Saved organization "work": Acme Mapping (ID: 1234567890) in profile "me"'
        in caplog.text
    )
    # Never written into MAPOrganizationKey, which would send every upload of the
    # profile to the organization
    assert "MAPOrganizationKey" not in config_path.read_text()

    caplog.clear()
    # The only profile is selected without --user_name
    user_items = authenticate.fetch_user_items(organization_name="work")
    assert user_items["MAPOrganizationKey"] == "1234567890"
    # The saved ID is checked again
    assert fetched == ["1234567890", "1234567890"]
    assert "Uploading to organization: Acme Mapping (ID: 1234567890)" in caplog.text
    assert "Saved organization" not in caplog.text


def test_save_overrides_a_name_saved_with_another_id(
    config_path: Path, fetched: list[str], caplog: pytest.LogCaptureFixture
):
    _add_profile("me", **{"MAPOrganization.work": "1234567890"})

    user_items = authenticate.fetch_user_items(
        user_name="me", organization_key="2222222222", organization_name="work"
    )

    assert user_items["MAPOrganizationKey"] == "2222222222"
    assert _saved("me") == {"work": "2222222222"}
    [warning] = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warning.getMessage() == (
        'The organization "work" (ID: 1234567890) already exists in profile "me" and will be overridden'
    )


def test_save_the_id_as_the_server_returns_it(
    config_path: Path, fetched: list[str], caplog: pytest.LogCaptureFixture
):
    _add_profile("me")
    caplog.set_level(logging.INFO)

    user_items = authenticate.fetch_user_items(
        user_name="me", organization_key="01234567890", organization_name="work"
    )

    assert user_items["MAPOrganizationKey"] == "1234567890"
    assert _saved("me") == {"work": "1234567890"}
    assert (
        'Saved organization "work": Acme Mapping (ID: 1234567890) in profile "me"'
        in caplog.text
    )


def test_an_id_the_server_rejects_is_not_saved(config_path: Path, fetched: list[str]):
    _add_profile("me", **{"MAPOrganization.work": "1234567890"})
    before = config_path.read_text()

    with pytest.raises(requests.HTTPError):
        authenticate.fetch_user_items(
            user_name="me", organization_key="999", organization_name="work"
        )

    assert fetched == ["999"]
    assert config_path.read_text() == before


def test_save_the_same_id_again_does_not_rewrite_the_config(
    config_path: Path, fetched: list[str], caplog: pytest.LogCaptureFixture
):
    _add_profile("me", **{"MAPOrganization.work": "1234567890"})
    mtime_ns = config_path.stat().st_mtime_ns
    caplog.set_level(logging.INFO)

    authenticate.fetch_user_items(
        user_name="me", organization_key="1234567890", organization_name="work"
    )

    assert config_path.stat().st_mtime_ns == mtime_ns
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]
    assert 'Saved organization "work"' in caplog.text


def test_unknown_organization_name_lists_the_saved_ones(
    config_path: Path, fetched: list[str], capsys: pytest.CaptureFixture
):
    _add_profile("me", **{"MAPOrganization.work": "1234567890"})
    # A name saved in another profile does not count
    _add_profile("other", **{"MAPOrganization.home": "2222222222"})

    with pytest.raises(exceptions.MapillaryBadParameterError) as excinfo:
        authenticate.fetch_user_items(user_name="me", organization_name="home")

    assert str(excinfo.value) == (
        'Organization "home" not found in profile "me". '
        "To save it, give its ID with --organization_key ID --organization_name home"
    )
    listed = capsys.readouterr().err
    assert 'Saved organizations in profile "me":' in listed
    assert "work" in listed and "1234567890" in listed
    assert "2222222222" not in listed
    assert fetched == []


def test_unknown_organization_name_in_a_profile_without_saved_names(
    config_path: Path, fetched: list[str], capsys: pytest.CaptureFixture
):
    _add_profile("me")

    with pytest.raises(exceptions.MapillaryBadParameterError, match="not found"):
        authenticate.fetch_user_items(organization_name="work")

    assert 'No organizations saved in profile "me"' in capsys.readouterr().err


@pytest.mark.parametrize(
    "name",
    ["w", "x" * 33, "1work", "123", "_work", "-work", "wo rk", "work.x", "wörk", ""],
)
def test_invalid_organization_names(config_path: Path, fetched: list[str], name: str):
    _add_profile("me")
    before = config_path.read_text()

    for organization_key in ["1234567890", None]:
        with pytest.raises(
            exceptions.MapillaryBadParameterError, match="(?i)organization name"
        ):
            authenticate.fetch_user_items(
                user_name="me",
                organization_key=organization_key,
                organization_name=name,
            )

    assert fetched == []
    assert config_path.read_text() == before


@pytest.mark.parametrize("name", ["ab", "x" * 32, "My-Org_2", "a-", "Z_9"])
def test_valid_organization_names(config_path: Path, fetched: list[str], name: str):
    _add_profile("me")

    authenticate.fetch_user_items(
        user_name="me", organization_key="1234567890", organization_name=name
    )
    user_items = authenticate.fetch_user_items(user_name="me", organization_name=name)

    assert user_items["MAPOrganizationKey"] == "1234567890"
    assert _saved("me") == {name: "1234567890"}


def test_invalid_names_fail_before_the_login_prompt(
    config_path: Path, fetched: list[str], monkeypatch: pytest.MonkeyPatch
):
    def _no_login(*args, **kwargs):
        raise AssertionError("should not prompt for login")

    monkeypatch.setattr(authenticate, "_prompt_login", _no_login)

    with pytest.raises(exceptions.MapillaryBadParameterError):
        authenticate.fetch_user_items(organization_name="1work")
    with pytest.raises(exceptions.MapillaryBadParameterError):
        authenticate.fetch_user_items(organization_key="work")

    assert not config_path.exists()


@pytest.mark.parametrize("organization_key", ["work", "12a4", "-123", "١٢٣", ""])
def test_organization_key_takes_only_an_id(
    config_path: Path,
    fetched: list[str],
    capsys: pytest.CaptureFixture,
    organization_key: str,
):
    _add_profile("me", **{"MAPOrganization.work": "1234567890"})
    before = config_path.read_text()

    with pytest.raises(exceptions.MapillaryBadParameterError) as excinfo:
        authenticate.fetch_user_items(user_name="me", organization_key=organization_key)

    assert str(excinfo.value) == (
        "--organization_key takes an organization ID; "
        "for a saved name use --organization_name NAME"
    )
    listed = capsys.readouterr().err
    assert "work" in listed and "1234567890" in listed
    assert fetched == []
    assert config_path.read_text() == before


def test_organization_key_takes_only_an_id_lists_all_profiles(
    config_path: Path, fetched: list[str], capsys: pytest.CaptureFixture
):
    # No profile selected without the prompt: list the names saved in each profile
    _add_profile("me", **{"MAPOrganization.work": "1234567890"})
    _add_profile("other", **{"MAPOrganization.home": "2222222222"})

    with pytest.raises(
        exceptions.MapillaryBadParameterError, match="takes an organization ID"
    ):
        authenticate.fetch_user_items(organization_key="work")

    listed = capsys.readouterr().err
    assert "Existing Mapillary profiles:" in listed
    assert "organization work" in listed and "1234567890" in listed
    assert "organization home" in listed and "2222222222" in listed
    assert fetched == []


def test_organization_key_alone_saves_nothing(
    config_path: Path, fetched: list[str], caplog: pytest.LogCaptureFixture
):
    _add_profile("me", **{"MAPOrganization.work": "1234567890"})
    before = config_path.read_bytes()
    caplog.set_level(logging.INFO)

    user_items = authenticate.fetch_user_items(
        user_name="me", organization_key="2222222222"
    )

    assert user_items["MAPOrganizationKey"] == "2222222222"
    assert fetched == ["2222222222"]
    assert config_path.read_bytes() == before
    assert "Uploading to organization: Other Org (ID: 2222222222)" in caplog.text
    assert (
        "To upload to this organization by a name next time, add --organization_name NAME"
        in caplog.text
    )

    caplog.clear()
    authenticate.fetch_user_items(user_name="me", organization_key="1234567890")
    assert config_path.read_bytes() == before
    assert (
        'This organization is saved in profile "me" as "work": next time you can use --organization_name work'
        in caplog.text
    )


def test_profile_default_organization_still_applies(
    config_path: Path, fetched: list[str]
):
    # A MAPOrganizationKey line in a profile sends every upload of the profile to
    # that organization, unchecked
    _add_profile(
        "me", MAPOrganizationKey="1234567890", **{"MAPOrganization.other": "2222222222"}
    )

    user_items = authenticate.fetch_user_items(user_name="me")
    assert user_items["MAPOrganizationKey"] == "1234567890"
    assert fetched == []

    # A saved name overrides it, for this upload only
    user_items = authenticate.fetch_user_items(
        user_name="me", organization_name="other"
    )
    assert user_items["MAPOrganizationKey"] == "2222222222"

    # Saving a name leaves it as it is
    authenticate.fetch_user_items(
        user_name="me", organization_key="2222222222", organization_name="new"
    )
    user_items_in_config = config.load_user("me")
    assert user_items_in_config is not None
    assert user_items_in_config["MAPOrganizationKey"] == "1234567890"
    assert authenticate.fetch_user_items(user_name="me")["MAPOrganizationKey"] == (
        "1234567890"
    )


def test_names_are_saved_in_the_selected_profile(
    config_path: Path, fetched: list[str], monkeypatch: pytest.MonkeyPatch
):
    _add_profile("me", **{"MAPOrganization.work": "1234567890"})
    _add_profile("other", **{"MAPOrganization.work": "2222222222"})

    # Multiple profiles, no --user_name and no prompt
    with pytest.raises(
        exceptions.MapillaryBadParameterError, match="Multiple user profiles"
    ):
        authenticate.fetch_user_items(organization_name="work")

    user_items = authenticate.fetch_user_items(
        user_name="other", organization_name="work"
    )
    assert user_items["MAPOrganizationKey"] == "2222222222"

    # The profile chosen at the prompt
    _enable_prompt(monkeypatch, ["1"])
    user_items = authenticate.fetch_user_items(organization_name="work")
    assert user_items["MAPOrganizationKey"] == "1234567890"

    _enable_prompt(monkeypatch, ["other"])
    authenticate.fetch_user_items(
        organization_key="1234567890", organization_name="new"
    )
    assert _saved("me") == {"work": "1234567890"}
    assert _saved("other") == {"work": "2222222222", "new": "1234567890"}


def test_login_prompt_runs_first_without_a_profile(
    config_path: Path, fetched: list[str], monkeypatch: pytest.MonkeyPatch
):
    _enable_prompt(monkeypatch, ["me", "me@example.com"])
    monkeypatch.setattr(authenticate.getpass, "getpass", lambda prompt: "password")

    def _get_upload_token(
        client_session: requests.Session, email: str, password: str
    ) -> requests.Response:
        assert (email, password) == ("me@example.com", "password")
        resp = requests.Response()
        resp.status_code = 200
        resp._content = json.dumps(
            {"access_token": "new_token", "user_id": 42}
        ).encode()
        return resp

    monkeypatch.setattr(api_v4, "get_upload_token", _get_upload_token)

    user_items = authenticate.fetch_user_items(
        organization_key="1234567890", organization_name="work"
    )

    assert user_items["MAPOrganizationKey"] == "1234567890"
    assert config.load_user("me") == {
        "user_upload_token": "new_token",
        "MAPSettingsUserKey": "42",
        "MAPOrganization.work": "1234567890",
    }


def test_authenticate_again_keeps_saved_organizations(config_path: Path):
    _add_profile(
        "me",
        MAPOrganizationKey="2222222222",
        **{"MAPOrganization.work": "1234567890"},
    )

    authenticate.authenticate(user_name="me", jwt="new_token")

    assert config.load_user("me") == {
        "user_upload_token": "new_token",
        "MAPOrganizationKey": "2222222222",
        "MAPOrganization.work": "1234567890",
    }


def test_authenticate_lists_saved_organizations(
    config_path: Path, capsys: pytest.CaptureFixture
):
    _add_profile(
        "me",
        MAPSettingsUserKey="1001",
        **{"MAPOrganization.work": "1234567890", "MAPOrganization.home": "2222222222"},
    )
    _add_profile("other", MAPSettingsUserKey="1002")

    authenticate.authenticate(user_name="new", jwt="new_token")

    lines = capsys.readouterr().err.splitlines()
    assert lines[0] == "Existing Mapillary profiles:"
    me = next(i for i, line in enumerate(lines) if " me " in line)
    assert "1001" in lines[me]
    assert lines[me + 1].split() == ["organization", "work", "1234567890"]
    assert lines[me + 2].split() == ["organization", "home", "2222222222"]
    assert lines[me + 3].split()[:3] == ["2.", "other", "1002"]


def test_authenticate_deletes_only_the_organization_name(
    config_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    _add_profile(
        "me",
        MAPOrganizationKey="2222222222",
        **{"MAPOrganization.work": "1234567890", "MAPOrganization.home": "2222222222"},
    )
    _add_profile("other", **{"MAPOrganization.work": "2222222222"})
    caplog.set_level(logging.INFO)

    def _no_login(*args, **kwargs):
        raise AssertionError("should not log in")

    monkeypatch.setattr(authenticate, "_prompt_login", _no_login)
    monkeypatch.setattr(authenticate, "_verify_user_auth", _no_login)

    authenticate.authenticate(user_name="me", organization_name="work", delete=True)

    assert config.load_user("me") == {
        "user_upload_token": "me_token",
        "MAPOrganizationKey": "2222222222",
        "MAPOrganization.home": "2222222222",
    }
    assert _saved("other") == {"work": "2222222222"}
    assert (
        'Deleted organization "work" (ID: 1234567890) from profile "me"' in caplog.text
    )

    with pytest.raises(
        exceptions.MapillaryBadParameterError,
        match='Organization "work" not found in profile "me"',
    ):
        authenticate.authenticate(user_name="me", organization_name="work", delete=True)

    with pytest.raises(
        exceptions.MapillaryBadParameterError, match='Profile "nobody" not found'
    ):
        authenticate.authenticate(
            user_name="nobody", organization_name="work", delete=True
        )


def test_authenticate_takes_organization_name_only_to_delete(config_path: Path):
    _add_profile("me")
    before = config_path.read_text()

    with pytest.raises(exceptions.MapillaryBadParameterError, match="--delete"):
        authenticate.authenticate(
            user_name="me", jwt="new_token", organization_name="work"
        )

    assert config_path.read_text() == before


@pytest.mark.parametrize(
    "command", ["upload", "process_and_upload", "video_process_and_upload"]
)
def test_upload_commands_take_organization_name(
    config_path: Path,
    fetched: list[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    command: str,
):
    _add_profile("me")
    uploaded: list[config.UserItem] = []

    def _upload(user_items: config.UserItem) -> None:
        uploaded.append(user_items)

    monkeypatch.setattr("mapillary_tools.commands.upload.upload", _upload)
    monkeypatch.setattr(ProcessCommand, "run", lambda self, vars_args: None)
    monkeypatch.setattr(VideoProcessCommand, "run", lambda self, vars_args: None)

    import_args = [str(tmp_path)]
    if command == "video_process_and_upload":
        import_args.append(str(tmp_path.joinpath("samples")))

    for args in [
        ["--organization_key", "1234567890", "--organization_name", "work"],
        ["--organization_name", "work"],
    ]:
        monkeypatch.setattr(
            sys, "argv", ["mapillary_tools", command, *import_args, *args]
        )
        commands.main()

    assert [u["MAPOrganizationKey"] for u in uploaded] == ["1234567890"] * 2
    assert _saved("me") == {"work": "1234567890"}


def test_upload_history_records_the_saved_organization(
    config_path: Path,
    fetched: list[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    _add_profile("me")
    history_path = tmp_path.joinpath("history")
    upload_path = tmp_path.joinpath("uploads")
    upload_path.mkdir()
    monkeypatch.setattr(constants, "MAPILLARY_UPLOAD_HISTORY_PATH", str(history_path))
    monkeypatch.setattr(constants, "MAPILLARY__ENABLE_UPLOAD_HISTORY_FOR_DRY_RUN", True)
    monkeypatch.setenv("MAPILLARY_UPLOAD_ENDPOINT", str(upload_path))

    image_dir = tmp_path.joinpath("images")
    image_dir.mkdir()
    descs = []
    for idx, name in enumerate(["DSC00001.JPG", "DSC00497.JPG"]):
        shutil.copy(TEST_IMAGE_DIR.joinpath(name), image_dir)
        descs.append(
            {
                "filename": str(image_dir.joinpath(name)),
                "filetype": "image",
                "MAPLatitude": 58.5927694 + idx * 0.0001,
                "MAPLongitude": 16.1840944,
                "MAPCaptureTime": f"2021_02_13_13_24_4{idx}_000",
                "MAPSequenceUUID": "sequence",
                "filesize": image_dir.joinpath(name).stat().st_size,
            }
        )
    desc_path = tmp_path.joinpath("descs.json")
    desc_path.write_text(json.dumps(descs))
    # Valid descriptions
    assert DescriptionJSONSerializer.deserialize(desc_path.read_bytes())

    # Save, then use
    for args in [
        ["--organization_key", "1234567890", "--organization_name", "work"],
        ["--organization_name", "work"],
    ]:
        shutil.rmtree(history_path, ignore_errors=True)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "mapillary_tools",
                "upload",
                str(image_dir),
                *["--desc_path", str(desc_path)],
                "--dry_run",
                *args,
            ],
        )
        commands.main()

        [record] = [json.loads(p.read_text()) for p in history_path.glob("*/*.json")]
        assert record["params"]["organization_key"] == "1234567890"

    assert fetched == ["1234567890", "1234567890"]
