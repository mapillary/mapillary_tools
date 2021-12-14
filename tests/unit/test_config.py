import py.path

from mapillary_tools import config


def test_config_list_all_users(tmpdir: py.path.local):
    c = tmpdir.join("empty_config.ini")
    x = config.list_all_users(config_path=str(c))
    assert not x

    config.update_config(
        "hello",
        {
            "ThisIsOption": "1",
        },
        config_path=str(c),
    )

    x = config.list_all_users(config_path=str(c))
    assert len(x) == 1
    assert x[0] == {"ThisIsOption": "1"}


def test_update_config(tmpdir: py.path.local):
    c = tmpdir.join("empty_config.ini")
    config.update_config("world", {"ThisIsOption": "hello"}, config_path=str(c))
    x = config.load_user("world", config_path=str(c))
    assert x == {"ThisIsOption": "hello"}

    config.update_config("world", {"ThisIsOption": "world2"}, config_path=str(c))
    x = config.load_user("world", config_path=str(c))
    assert x == {"ThisIsOption": "world2"}


def test_load_user(tmpdir: py.path.local):
    c = tmpdir.join("empty_config.ini")
    config.update_config("world", {"ThisIsOption": "hello"}, config_path=str(c))
    x = config.load_user("hello", config_path=str(c))
    assert x is None
    x = config.load_user("world", config_path=str(c))
    assert x == {"ThisIsOption": "hello"}
