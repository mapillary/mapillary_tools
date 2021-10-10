import uuid
import datetime
import itertools
import typing as T

from mapillary_tools import process_sequence_properties as psp, types


def make_image_desc(
    lng: float, lat: float, time: float, angle: float = None, filename: str = None
) -> types.FinalImageDescriptionOrError:
    if filename is None:
        filename = str(uuid.uuid4())

    desc = {
        "MAPLatitude": lat,
        "MAPLongitude": lng,
        "MAPCaptureTime": types.datetime_to_map_capture_time(
            datetime.datetime.fromtimestamp(time)
        ),
        "filename": filename,
    }
    if angle is not None:
        desc["MAPCompassHeading"] = {
            "TrueHeading": angle,
            "MagneticHeading": angle,
        }
    return T.cast(types.FinalImageDescriptionOrError, desc)


def test_find_sequences_by_folder():
    sequence = [
        {"error": "hello"},
        # s1
        make_image_desc(1.00001, 1.00001, 2, filename="hello/foo.jpg"),
        make_image_desc(1.00002, 1.00002, 2, filename="hello/bar.jpg"),
        make_image_desc(1.00002, 1.00002, 2, filename="hello/"),
        # s2
        make_image_desc(1.00001, 1.00001, 2, filename="foo.jpg"),
        # s3
        make_image_desc(1.00001, 1.00001, 19, filename="/foo.jpg"),
        make_image_desc(1.00002, 1.00002, 28, filename="/bar.jpg"),
    ]
    descs = psp.process_sequence_properties(
        sequence,
        cutoff_distance=1000000,
        cutoff_time=10000,
        interpolate_directions=False,
        duplicate_distance=0,
        duplicate_angle=0,
    )
    assert len(descs) == len(sequence)
    descs = [d for d in descs if "error" not in d]

    descs.sort(key=lambda d: d["MAPSequenceUUID"])
    actual_seqs = []
    for key, seq in itertools.groupby(descs, key=lambda d: d["MAPSequenceUUID"]):
        actual_seqs.append(list(seq))
    actual_seqs.sort(key=lambda s: s[0]["filename"])
    assert {"/foo.jpg", "/bar.jpg"} == set(d["filename"] for d in actual_seqs[0])
    assert {"foo.jpg"} == set(d["filename"] for d in actual_seqs[1])
    assert {"hello/foo.jpg", "hello/bar.jpg", "hello/"} == set(
        d["filename"] for d in actual_seqs[2]
    )


def test_cut_sequences():
    sequence = [
        # s1
        make_image_desc(1, 1, 1),
        make_image_desc(1.00001, 1.00001, 2),
        make_image_desc(1.00002, 1.00002, 2),
        # s2
        make_image_desc(1.00090, 1.00090, 2),
        make_image_desc(1.00091, 1.00091, 3),
        # s3
        make_image_desc(1.00092, 1.00092, 19),
        make_image_desc(1.00093, 1.00093, 28),
    ]
    descs = psp.process_sequence_properties(
        sequence,
        cutoff_distance=100,
        cutoff_time=10,
        interpolate_directions=False,
        duplicate_distance=0,
        duplicate_angle=0,
    )
    actual_seqs = []
    for key, seq in itertools.groupby(descs, key=lambda d: d["MAPSequenceUUID"]):
        actual_seqs.append(list(seq))
    assert len(actual_seqs) == 3
    actual_seqs.sort(key=lambda d: d[0]["MAPCaptureTime"])
    assert [img["filename"] for img in sequence[0:3]] == [
        img["filename"] for img in actual_seqs[0]
    ]
    assert [img["filename"] for img in sequence[3:5]] == [
        img["filename"] for img in actual_seqs[1]
    ]
    assert [img["filename"] for img in sequence[5:7]] == [
        img["filename"] for img in actual_seqs[2]
    ]


def test_duplication():
    sequence = [
        # s1
        make_image_desc(1, 1, 1, angle=0),
        make_image_desc(1.00001, 1.00001, 2, angle=1),
        make_image_desc(1.00002, 1.00002, 2, angle=-1),
        make_image_desc(1.00003, 1.00003, 2, angle=-2),
        make_image_desc(1.00009, 1.00009, 2, angle=5),
        make_image_desc(1.00090, 1.00090, 2, angle=5),
        make_image_desc(1.00091, 1.00091, 2, angle=-1),
    ]
    descs = psp.process_sequence_properties(
        sequence,
        cutoff_distance=100000,
        cutoff_time=100,
        interpolate_directions=False,
        duplicate_distance=100,
        duplicate_angle=5,
    )
    assert len(descs) == len(sequence)
    assert len([d for d in descs if "error" in d]) == 4
    assert set(d["filename"] for d in sequence[1:-2]) == set(
        d["error"]["vars"]["desc"]["filename"] for d in descs if "error" in d
    )


def test_interpolation():
    sequence = [
        # s1
        make_image_desc(0, 0, 1, angle=2),
        make_image_desc(1, 0, 2, angle=123),
        make_image_desc(1, 1, 3, angle=344),
        make_image_desc(0, 1, 4, angle=22),
        make_image_desc(0, 0, 5, angle=-123),
    ]
    descs = psp.process_sequence_properties(
        sequence,
        cutoff_distance=1000000000,
        cutoff_time=100,
        interpolate_directions=True,
        duplicate_distance=100,
        duplicate_angle=5,
    )
    descs.sort(key=lambda d: d["MAPCaptureTime"])
    assert [90, 0, 270, 180, 180] == [
        int(desc["MAPCompassHeading"]["TrueHeading"]) for desc in descs
    ]


def test_interpolation_single():
    sequence = [
        # s1
        make_image_desc(0, 0, 1, angle=123),
    ]
    descs = psp.process_sequence_properties(
        sequence,
        cutoff_distance=1000000000,
        cutoff_time=100,
        interpolate_directions=True,
        duplicate_distance=100,
        duplicate_angle=5,
    )
    assert [123] == [int(desc["MAPCompassHeading"]["TrueHeading"]) for desc in descs]




def test_geotag_from_gpx_2():
    images = [
        make_image_desc(0, 0, 1),
        make_image_desc(0, 0, 4),
        make_image_desc(0, 0, 9),
        make_image_desc(0, 0, 17),
        make_image_desc(0, 0, 40),
    ]
    image_by_filename = {image["filename"]: image for image in images}

    from mapillary_tools.geotag.geotag_from_gpx import GeotagFromGPX

    class GeotagFromGPXTest(GeotagFromGPX):
        def read_image_capture_time(self, image):
            return types.map_capture_time_to_datetime(image_by_filename[image]["MAPCaptureTime"])

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

    geotag = GeotagFromGPXTest(image_dir=".", images=[d["filename"] for d in images], points=points)
    descs = geotag.to_description()
    descs.sort(key=lambda d: d["MAPCaptureTime"])

    assert descs[0]["MAPLatitude"] == 1.3
    assert descs[0]["MAPLongitude"] == 1
    assert descs[0]["MAPCaptureTime"] == "1970_01_01_00_01_40_000"
    #
    assert abs(descs[1]["MAPLatitude"] - 2.5) < 0.0001
    assert abs(descs[1]["MAPLongitude"] - 2) < 0.001
    assert descs[1]["MAPCaptureTime"] == "1970_01_01_00_01_43_000"

    assert abs(descs[2]["MAPLatitude"] - 4) < 0.0001
    assert abs(descs[2]["MAPLongitude"] - 3.0769230769230766) < 0.001
    assert descs[2]["MAPCaptureTime"] == "1970_01_01_00_01_48_000"

    assert abs(descs[3]["MAPLatitude"] - 4) < 0.0001
    assert abs(descs[3]["MAPLongitude"] - 5.230769230769231) < 0.001
    assert descs[3]["MAPCaptureTime"] == "1970_01_01_00_01_56_000"

    assert abs(descs[4]["MAPLatitude"] - 4) < 0.0001
    assert abs(descs[4]["MAPLongitude"] - 11.423076923076923) < 0.001
    assert descs[4]["MAPCaptureTime"] == "1970_01_01_00_02_19_000"
