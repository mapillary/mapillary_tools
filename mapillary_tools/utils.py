def force_decode(string, codecs=['utf8', 'cp1252']):
    for i in codecs:
        try:
            return string.decode(i)
        except UnicodeDecodeError:
            pass
    print('cannot decode string: %s' % (string))
    return string.decode('utf8', errors='replace')