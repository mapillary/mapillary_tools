def force_decode(string, codecs=None):
    if codecs is None:
        codecs = ["utf8", "cp1252"]
    if isinstance(string, str):
        return string
    for i in codecs:
        try:
            return string.decode(i)
        except UnicodeDecodeError:
            pass
    print(f"cannot decode string: {string}")
    return string.decode("utf8", errors="replace")
