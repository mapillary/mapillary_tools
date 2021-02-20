import requests


def create_upload_session(upload_type, metadata, options):
    url = _get_url(options, "/v3/me/uploads")
    headers = _get_headers(options)
    params = _get_params(options)
    json = {"type": upload_type, "metadata": metadata}

    return requests.post(url, params=params, headers=headers, json=json)


def close_upload_session(session, json, options):
    url = _get_url(options, "/v3/me/uploads")
    url = "{}/{}/closed".format(url, session["key"])
    headers = _get_headers(options)
    params = _get_params(options)

    return requests.put(url, params=params, headers=headers, json=json)


def get_upload_session(session, options):
    url = _get_url(options, "/v3/me/uploads")
    url = "{}/{}".format(url, session["key"])
    headers = _get_headers(options)
    params = _get_params(options)

    return requests.get(url, params=params, headers=headers)


def upload_file(session, file_path, object_key):
    with open(file_path, "rb") as f:
        files = {"file": (object_key, f)}
        data = session["fields"].copy()
        data["key"] = session["key_prefix"] + object_key
        resp = requests.post(session["url"], data=data, files=files)

    return resp


def _get_url(options, resource):
    endpoint = options.get("endpoint", "https://a.mapillary.com")
    url = endpoint + resource

    return url


def _get_headers(options):
    token = options["token"]
    headers = {"Authorization": "Bearer " + token}

    return headers


def _get_params(options):
    client_id = options["client_id"]
    params = {"client_id": client_id}

    return params
