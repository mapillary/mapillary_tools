import requests


def create_upload_session(upload_type, metadata, options):
    url = _get_url(options, "/v3/me/uploads")
    headers = _get_headers(options)
    json = {"type": upload_type, "metadata": metadata}

    return requests.post(url, headers=headers, json=json)


def close_upload_session(session, json, options):
    url = _get_url(options, "/v3/me/uploads")
    url = "{}/{}/closed".format(url, session["key"])
    headers = _get_headers(options)

    return requests.put(url, headers=headers, json=json)


def upload_file(session, file_path, object_key):
    with open(file_path, 'rb') as f:
        files = {'file': (object_key, f)}
        data = session['fields'].copy()
        data['key'] = session['key_prefix'] + object_key
        resp = requests.post(session['url'], data=data, files=files)

    return resp


def _get_url(options, resource):
    endpoint = options.get("endpoint", "https://a.mapillary.com")
    url = endpoint + resource

    return url


def _get_headers(options):
    token = options["token"]
    headers = {"Authorization": "Bearer " + token}

    return headers
