import binascii
import datetime
import struct

# author https://github.com/stilldavid

"""
does the heavy lifting of parsing the GPMF format from a binary file
"""


def parse_gps(toparse: bytes, data: dict, scale):
    gps = struct.unpack(">lllll", toparse)

    data["gps"].append(
        {
            "lat": float(gps[0]) / scale[0],
            "lon": float(gps[1]) / scale[1],
            "alt": float(gps[2]) / scale[3],
            "spd": float(gps[3]) / scale[3],
            "s3d": float(gps[4]) / scale[4],
        }
    )


def parse_time(toparse: bytes, data: dict, scale):
    datetime_object = datetime.datetime.strptime(
        toparse.decode("utf-8"), "%y%m%d%H%M%S.%f"
    )
    data["time"] = datetime_object


def parse_accl(toparse: bytes, data: dict, scale):
    # todo: fusion
    if 6 == len(toparse):
        data["accl"] = struct.unpack(">hhh", toparse)


def parse_gyro(toparse: bytes, data: dict, scale):
    # todo: fusion
    if 6 == len(toparse):
        data["gyro"] = struct.unpack(">hhh", toparse)


def parse_fix(toparse: bytes, data: dict, scale):
    data["gps_fix"] = struct.unpack(">I", toparse)[0]


def parse_precision(toparse: bytes, data: dict, scale):
    data["gps_precision"] = struct.unpack(">H", toparse)[0]


"""
since we only get 1Hz timestamps and ~18Hz GPS, interpolate timestamps
in between known good times.

Sometimes it's 18Hz, sometimes 19Hz, so peek at the next row and grab their
timestamp. On the last one, just add 1 second as a best guess, worst case it's
off by ~50 milliseconds
"""


def interpolate_times(frame, until):
    tot = len(frame["gps"])
    diff = until - frame["time"]
    offset = diff / tot

    for i, row in enumerate(frame["gps"]):
        toadd = datetime.timedelta(microseconds=(offset.microseconds * i))
        frame["gps"][i]["time"] = frame["time"] + toadd


def parse_bin(path: str) -> list:
    # f = open(path, "rb")

    s: dict = {}  # the current Scale data to apply to next requester
    output = []

    # handlers for various fourCC codes
    methods = {
        b"GPS5": parse_gps,
        b"GPSU": parse_time,
        b"GPSF": parse_fix,
        b"GPSP": parse_precision,
        b"ACCL": parse_accl,
        b"GYRO": parse_gyro,
    }

    d: dict = {"gps": []}  # up to date dictionary, iterate and fill then flush

    with open(path, "rb") as f:
        while True:
            label: bytes = f.read(4)
            if not label:  # eof
                break

            desc: bytes = f.read(4)
            if not desc:  # eof
                break

            # null length
            if b"00" == binascii.hexlify(desc[:1]):
                continue

            val_size: int = struct.unpack(">b", desc[1:2])[0]
            num_values: int = struct.unpack(">h", desc[2:4])[0]
            length = val_size * num_values

            if label == b"DVID":
                if len(d["gps"]):  # first one is empty
                    output.append(d)
                d = {"gps": []}  # reset

            for i in range(num_values):
                data: bytes = f.read(val_size)

                if label in methods:
                    methods[label](data, d, s)

                if label == b"SCAL":
                    if 2 == val_size:
                        s[i] = struct.unpack(">h", data)[0]
                    elif 4 == val_size:
                        s[i] = struct.unpack(">i", data)[0]
                    else:
                        raise Exception("unknown scal size")

            # pack
            mod = length % 4
            if mod != 0:
                seek = 4 - mod
                f.read(seek)  # discarded

    return output
