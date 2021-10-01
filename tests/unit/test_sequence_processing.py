import uuid
import datetime
import itertools

from mapillary_tools import process_sequence_properties as psp
from mapillary_tools.types import (
    Image,
    datetime_to_map_capture_time,
    map_capture_time_to_datetime,
)
from mapillary_tools import image_log, types


def make_image(
    lng: float, lat: float, time: float, angle: float = None, filename: str = None
):
    if filename is None:
        filename = str(uuid.uuid4())

    desc: Image = {
        "MAPLatitude": lat,
        "MAPLongitude": lng,
        "MAPCaptureTime": datetime_to_map_capture_time(
            datetime.datetime.fromtimestamp(time)
        ),
    }
    if angle is not None:
        desc["MAPCompassHeading"] = {
            "TrueHeading": angle,
            "MagneticHeading": angle,
        }
    return psp._GPXPoint(desc, filename=filename)


def test_split_sequences():
    sequence = [
        # s1
        make_image(1, 1, 1),
        make_image(1.00001, 1.00001, 2),
        make_image(1.00002, 1.00002, 2),
        # s2
        make_image(1.00090, 1.00090, 2),
        make_image(1.00091, 1.00091, 3),
        # s3
        make_image(1.00092, 1.00092, 19),
        make_image(1.00093, 1.00093, 28),
    ]
    psp.process_sequence(
        sequence,
        cutoff_distance=100,
        cutoff_time=10,
        interpolate_directions=False,
        duplicate_distance=0,
        duplicate_angle=0,
    )
    descs = []
    for image in sequence:
        status, desc = image_log.read_process_data_from_memory(
            image.filename, "sequence_process"
        )
        assert status == "success", desc
        descs.append({**desc, "_filename": image.filename})
    actual_seqs = []
    for key, seq in itertools.groupby(descs, key=lambda d: d["MAPSequenceUUID"]):
        actual_seqs.append(list(seq))
    assert len(actual_seqs) == 3
    assert [img.filename for img in sequence[0:3]] == [
        img["_filename"] for img in actual_seqs[0]
    ]
    assert [img.filename for img in sequence[3:5]] == [
        img["_filename"] for img in actual_seqs[1]
    ]
    assert [img.filename for img in sequence[5:7]] == [
        img["_filename"] for img in actual_seqs[2]
    ]


def test_duplication():
    sequence = [
        # s1
        make_image(1, 1, 1, angle=0),
        make_image(1.00001, 1.00001, 2, angle=1),
        make_image(1.00002, 1.00002, 2, angle=-1),
        make_image(1.00003, 1.00003, 2, angle=-2),
        make_image(1.00009, 1.00009, 2, angle=5),
        make_image(1.00090, 1.00090, 2, angle=5),
        make_image(1.00091, 1.00091, 2, angle=-1),
    ]
    psp.process_sequence(
        sequence,
        cutoff_distance=100000,
        cutoff_time=100,
        interpolate_directions=False,
        duplicate_distance=100,
        duplicate_angle=5,
    )
    descs = []
    for image in sequence:
        status, desc = image_log.read_process_data_from_memory(
            image.filename, "sequence_process"
        )
        descs.append((status, desc))

    assert descs[0][0] == "success"
    assert descs[1][0] == "failed"
    assert descs[1][1]["type"] == "MapillaryDuplicationError"

    assert descs[2][0] == "failed"
    assert descs[2][1]["type"] == "MapillaryDuplicationError"

    assert descs[3][0] == "failed"
    assert descs[3][1]["type"] == "MapillaryDuplicationError"

    assert descs[4][0] == "failed"
    assert descs[4][1]["type"] == "MapillaryDuplicationError"

    assert descs[5][0] == "success"
    assert descs[6][0] == "success"


def test_interpolation():
    sequence = [
        # s1
        make_image(0, 0, 1, angle=2),
        make_image(1, 0, 2, angle=123),
        make_image(1, 1, 2, angle=344),
        make_image(0, 1, 2, angle=22),
        make_image(0, 0, 2, angle=-123),
    ]
    psp.process_sequence(
        sequence,
        cutoff_distance=1000000000,
        cutoff_time=100,
        interpolate_directions=True,
        duplicate_distance=100,
        duplicate_angle=5,
    )
    descs = []
    for image in sequence:
        status, desc = image_log.read_process_data_from_memory(
            image.filename, "sequence_process"
        )
        assert status == "success", desc
        descs.append(desc)

    assert [90, 0, 270, 180, 180] == [
        int(desc["MAPCompassHeading"]["TrueHeading"]) for desc in descs
    ]


def test_interpolation_single():
    sequence = [
        # s1
        make_image(0, 0, 1, angle=123),
    ]
    psp.process_sequence(
        sequence,
        cutoff_distance=1000000000,
        cutoff_time=100,
        interpolate_directions=True,
        duplicate_distance=100,
        duplicate_angle=5,
    )
    descs = []
    for image in sequence:
        status, desc = image_log.read_process_data_from_memory(
            image.filename, "sequence_process"
        )
        assert status == "success", desc
        descs.append(desc)
    assert [123] == [int(desc["MAPCompassHeading"]["TrueHeading"]) for desc in descs]


def test_geotag_from_gpx_2():
    from mapillary_tools.processing import _geotag_from_gpx

    images = [
        make_image(0, 0, 1),
        make_image(0, 0, 4),
        make_image(0, 0, 9),
        make_image(0, 0, 17),
        make_image(0, 0, 40),
    ]
    image_by_filename = {image.filename: image for image in images}

    points = [
        types.GPXPoint(
            lon=1, lat=1.3, time=datetime.datetime.utcfromtimestamp(100), alt=1
        ),
        types.GPXPoint(
            lon=2, lat=1, time=datetime.datetime.utcfromtimestamp(102), alt=2
        ),
        types.GPXPoint(
            lon=2, lat=4, time=datetime.datetime.utcfromtimestamp(104), alt=3
        ),
        types.GPXPoint(
            lon=9, lat=4, time=datetime.datetime.utcfromtimestamp(130), alt=3
        ),
    ]

    def _read_image_time(image: str):
        return map_capture_time_to_datetime(
            image_by_filename[image].desc["MAPCaptureTime"]
        )

    _geotag_from_gpx(
        [image.filename for image in images],
        points,
        offset_time=100,
        offset_angle=369,
        read_image_time=_read_image_time,
    )
    descs = []
    for image in images:
        ret = image_log.read_process_data_from_memory(image.filename, "geotag_process")
        status, desc = ret
        assert status == "success"
        descs.append(desc)

    assert descs[0]["MAPLatitude"] == 1.3
    assert descs[0]["MAPLongitude"] == 1
    assert descs[0]["MAPCaptureTime"] == "1970_01_01_00_03_20_000"
    #
    assert abs(descs[1]["MAPLatitude"] - 2.5) < 0.0001
    assert abs(descs[1]["MAPLongitude"] - 2) < 0.001
    assert descs[1]["MAPCaptureTime"] == "1970_01_01_00_03_23_000"

    assert abs(descs[2]["MAPLatitude"] - 4) < 0.0001
    assert abs(descs[2]["MAPLongitude"] - 3.0769230769230766) < 0.001
    assert descs[2]["MAPCaptureTime"] == "1970_01_01_00_03_28_000"

    assert abs(descs[3]["MAPLatitude"] - 4) < 0.0001
    assert abs(descs[3]["MAPLongitude"] - 5.230769230769231) < 0.001
    assert descs[3]["MAPCaptureTime"] == "1970_01_01_00_03_36_000"

    assert abs(descs[4]["MAPLatitude"] - 4) < 0.0001
    assert abs(descs[4]["MAPLongitude"] - 11.423076923076923) < 0.001
    assert descs[4]["MAPCaptureTime"] == "1970_01_01_00_03_59_000"
