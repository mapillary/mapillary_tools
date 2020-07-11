def force_decode(string, codecs=None):
    if codecs is None:
        codecs = ['utf8', 'cp1252']
    if isinstance(string, str):
        return string
    for i in codecs:
        try:
            return string.decode(i)
        except UnicodeDecodeError:
            pass
    print('cannot decode string: %s' % (string))
    return string.decode('utf8', errors='replace')


def format_orientation(orientation):
    """
    Convert orientation from clockwise degrees to exif tag

    # see http://sylvana.net/jpegcrop/exif_orientation.html
    """
    mapping = {
        0: 1,
        90: 8,
        180: 3,
        270: 6,
    }
    if orientation not in mapping:
        raise ValueError("Orientation value has to be 0, 90, 180, or 270")

    return mapping[orientation]