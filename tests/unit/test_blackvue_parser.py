import io

import mapillary_tools.geo as geo
from mapillary_tools import blackvue_parser
from mapillary_tools.mp4 import construct_mp4_parser as cparser


def test_parse_points():
    gps_data = b"""
        # GGA
    [1623057130221]$GPGGA,201205.00,3853.16949,N,07659.54604,W,2,10,0.82,7.7,M,-34.7,M,,0000*6F

        # GGA
    [1623057129253]$GPGGA,201204.00,3853.16945,N,07659.54371,W,2,10,0.99,10.2,M,-34.7,M,,0000*5C

    [1623057129253]$GPGSA,A,3,19,02,06,12,17,09,05,20,04,25,,,1.83,0.99,1.54*0C

    [1623057129253]$GPGSV,3,1,12,02,67,331,39,04,08,040,21,05,28,214,30,06,53,047,31*71

    [1623057129253]$GPGSV,3,2,12,09,23,071,28,12,48,268,41,17,17,124,26,19,38,117,35*78

    [1623057129253]$GPGSV,3,3,12,20,23,221,35,25,26,307,39,46,20,244,35,51,35,223,40*72

    [1623057129253]$GPGLL,3853.16945,N,07659.54371,W,201204.00,A,D*70

    [1623057129253]$GPRMC,201205.00,A,3853.16949,N,07659.54604,W,5.849,284.43,070621,,,D*76

    [1623057129253]$GPVTG,284.43,T,,M,5.849,N,10.833,K,D*08[1623057130221]

        # GGA
    [1623057130221]$GPGGA,201205.00,3853.16949,N,07659.54604,W,2,10,0.82,7.7,M,-34.7,M,,0000*6F

    # invalid line
    [1623057130221]$GPGGA,**&^%$%$&(&(*(&&(^^*^*^^*&^&*))))

    # invalid line
    [1623057130221]$GPGGA,\x00\x00\x1c\xff

    [1623057130221]$GPGSA,A,3,19,02,06,12,17,09,05,20,04,25,,,1.65,0.82,1.43*08
    """

    box = {"type": b"free", "data": [{"type": b"gps ", "data": gps_data}]}
    data = cparser.Box32ConstructBuilder({b"free": {}}).Box.build(box)
    info = blackvue_parser.extract_blackvue_info(io.BytesIO(data))
    assert info is not None
    assert [
        geo.Point(
            time=0.0, lat=38.8861575, lon=-76.99239516666667, alt=10.2, angle=None
        ),
        geo.Point(
            time=0.968, lat=38.88615816666667, lon=-76.992434, alt=7.7, angle=None
        ),
        geo.Point(
            time=0.968, lat=38.88615816666667, lon=-76.992434, alt=7.7, angle=None
        ),
    ] == list(info.gps or [])
