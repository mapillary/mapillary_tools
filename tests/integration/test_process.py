import json
import os
import subprocess
import zipfile
import hashlib

import pytest
import py.path
import exifread

EXECUTABLE = os.getenv(
    "MAPILLARY_TOOLS_EXECUTABLE", "python3 -m mapillary_tools.commands"
)
IMPORT_PATH = "tests/integration/mapillary_tools_process_images_provider/data"
USERNAME = "test_username_MAKE_SURE_IT_IS_UNIQUE_AND_LONG_AND_BORING"


@pytest.fixture
def setup_config(tmpdir: py.path.local):
    config_path = tmpdir.mkdir("configs").join("CLIENT_ID")
    os.environ["MAPILLARY_CONFIG_PATH"] = str(config_path)
    x = subprocess.run(
        f"{EXECUTABLE} authenticate --user_name {USERNAME} --jwt test_user_token",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    yield config_path
    if tmpdir.check():
        tmpdir.remove(ignore_errors=True)


@pytest.fixture
def setup_data(tmpdir: py.path.local):
    data_path = tmpdir.mkdir("data")
    source = py.path.local(IMPORT_PATH)
    source.copy(data_path)
    yield data_path
    if tmpdir.check():
        tmpdir.remove(ignore_errors=True)


def test_basic():
    for option in ["--version", "--help"]:
        x = subprocess.run(f"{EXECUTABLE} {option}", shell=True)
        assert x.returncode == 0, x.stderr


def test_process(setup_data: py.path.local):
    x = subprocess.run(
        f"{EXECUTABLE} process {setup_data}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    desc_path = os.path.join(setup_data, "mapillary_image_description.json")
    with open(desc_path) as fp:
        descs = json.load(fp)
    for desc in descs:
        assert "filename" in desc
        assert os.path.isfile(os.path.join(setup_data, desc["filename"]))


def validate_and_extract_zip(filename: str):
    basename = os.path.basename(filename)
    assert basename.startswith("mly_tools_"), filename
    assert basename.endswith(".zip"), filename
    ret = {}
    import tempfile

    with zipfile.ZipFile(filename) as zipf:
        with tempfile.TemporaryDirectory() as tempdir:
            zipf.extractall(path=tempdir)
            for name in os.listdir(tempdir):
                with open(os.path.join(tempdir, name), "rb") as fp:
                    tags = exifread.process_file(fp)
                    desc_tag = tags.get("Image ImageDescription")
                    assert desc_tag is not None, tags
                    desc = json.loads(str(desc_tag.values))
                    assert isinstance(desc.get("MAPLatitude"), (float, int)), desc
                    assert isinstance(desc.get("MAPLongitude"), (float, int)), desc
                    assert isinstance(desc.get("MAPCaptureTime"), str), desc
                    assert isinstance(desc.get("MAPCompassHeading"), dict), desc
                    for key in desc.keys():
                        assert key.startswith("MAP"), key
                    ret[name] = desc
    return ret


def test_zip(tmpdir: py.path.local, setup_data: py.path.local):
    zip_dir = tmpdir.mkdir("zip_dir")
    x = subprocess.run(
        f"{EXECUTABLE} process {setup_data}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    x = subprocess.run(
        f"{EXECUTABLE} zip {setup_data} {zip_dir}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    assert 0 < len(zip_dir.listdir())
    for file in zip_dir.listdir():
        validate_and_extract_zip(str(file))


def test_upload_image_dir(
    tmpdir: py.path.local, setup_config: py.path.local, setup_data: py.path.local
):
    os.environ["MAPILLARY_CONFIG_PATH"] = str(setup_config)
    upload_dir = tmpdir.mkdir("mapillary_public_uploads")
    os.environ["MAPILLARY_UPLOAD_PATH"] = str(upload_dir)
    x = subprocess.run(
        f"{EXECUTABLE} process {setup_data}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    x = subprocess.run(
        f"{EXECUTABLE} upload {setup_data} --dry_run --user_name={USERNAME}",
        shell=True,
    )
    for file in upload_dir.listdir():
        validate_and_extract_zip(str(file))
    assert x.returncode == 0, x.stderr


def test_upload_image_dir_twice(
    tmpdir: py.path.local, setup_config: py.path.local, setup_data: py.path.local
):
    os.environ["MAPILLARY_CONFIG_PATH"] = str(setup_config)
    upload_dir = tmpdir.mkdir("mapillary_public_uploads")
    os.environ["MAPILLARY_UPLOAD_PATH"] = str(upload_dir)
    x = subprocess.run(
        f"{EXECUTABLE} process {setup_data}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr

    md5sum_map = {}

    # first upload
    x = subprocess.run(
        f"{EXECUTABLE} upload {setup_data} --dry_run --user_name={USERNAME}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    for file in upload_dir.listdir():
        validate_and_extract_zip(str(file))
        md5sum_map[os.path.basename(file)] = file_md5sum(file)

    # expect the second upload to not produce new uploads
    x = subprocess.run(
        f"{EXECUTABLE} upload {setup_data} --dry_run --user_name={USERNAME}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    for file in upload_dir.listdir():
        validate_and_extract_zip(str(file))
        new_md5sum = file_md5sum(file)
        assert md5sum_map[os.path.basename(file)] == new_md5sum
    assert len(md5sum_map) == len(upload_dir.listdir())


def test_upload_zip(
    tmpdir: py.path.local, setup_data: py.path.local, setup_config: py.path.local
):
    os.environ["MAPILLARY_CONFIG_PATH"] = str(setup_config)
    upload_dir = tmpdir.mkdir("mapillary_public_uploads")
    os.environ["MAPILLARY_UPLOAD_PATH"] = str(upload_dir)
    zip_dir = tmpdir.mkdir("zip_dir")
    x = subprocess.run(
        f"{EXECUTABLE} process {setup_data}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    x = subprocess.run(
        f"{EXECUTABLE} zip {setup_data} {zip_dir}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    for zfile in zip_dir.listdir():
        x = subprocess.run(
            f"{EXECUTABLE} upload {zfile} --dry_run --user_name={USERNAME}",
            shell=True,
        )
        assert x.returncode == 0, x.stderr
    for file in upload_dir.listdir():
        validate_and_extract_zip(str(file))


def test_process_and_upload(
    tmpdir: py.path.local, setup_config: py.path.local, setup_data: py.path.local
):
    os.environ["MAPILLARY_CONFIG_PATH"] = str(setup_config)
    upload_dir = tmpdir.mkdir("mapillary_public_uploads")
    os.environ["MAPILLARY_UPLOAD_PATH"] = str(upload_dir)
    x = subprocess.run(
        f"{EXECUTABLE} process_and_upload {setup_data} --dry_run --user_name={USERNAME}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    for file in upload_dir.listdir():
        validate_and_extract_zip(str(file))


def test_time(setup_data: py.path.local):
    # before offset
    x = subprocess.run(
        f"{EXECUTABLE} process {setup_data}",
        shell=True,
    )
    desc_path = setup_data.join("mapillary_image_description.json")
    with open(desc_path) as fp:
        descs = json.load(fp)

    expected = {
        "DSC00001.JPG": "2018_06_08_13_24_10_000",
        "DSC00497.JPG": "2018_06_08_13_32_28_000",
        "V0370574.JPG": "2018_07_27_11_32_14_000",
    }

    for desc in descs:
        assert "filename" in desc
        assert expected[desc["filename"]] == desc["MAPCaptureTime"]

    # after offset
    x = subprocess.run(
        f"{EXECUTABLE} process {setup_data} --offset_time=2.5",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    desc_path = setup_data.join("mapillary_image_description.json")
    with open(desc_path) as fp:
        descs = json.load(fp)

    expected = {
        "DSC00001.JPG": "2018_06_08_13_24_12_500",
        "DSC00497.JPG": "2018_06_08_13_32_30_500",
        "V0370574.JPG": "2018_07_27_11_32_16_500",
    }

    for desc in descs:
        assert "filename" in desc
        assert expected[desc["filename"]] == desc["MAPCaptureTime"]

    # after offset
    x = subprocess.run(
        f"{EXECUTABLE} process {setup_data} --offset_time=-1.0",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    desc_path = setup_data.join("mapillary_image_description.json")
    with open(desc_path) as fp:
        descs = json.load(fp)

    expected = {
        "DSC00001.JPG": "2018_06_08_13_24_09_000",
        "DSC00497.JPG": "2018_06_08_13_32_27_000",
        "V0370574.JPG": "2018_07_27_11_32_13_000",
    }

    for desc in descs:
        assert "filename" in desc
        assert expected[desc["filename"]] == desc["MAPCaptureTime"]


def test_angle(setup_data: py.path.local):
    # before offset
    x = subprocess.run(
        f"{EXECUTABLE} process {setup_data}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    desc_path = setup_data.join("mapillary_image_description.json")
    with open(desc_path) as fp:
        descs = json.load(fp)
    expected = {
        "DSC00001.JPG": 270.89,
        "DSC00497.JPG": 271.27,
        "V0370574.JPG": 359.0,
    }
    for desc in descs:
        assert "filename" in desc
        assert (
            abs(expected[desc["filename"]] - desc["MAPCompassHeading"]["TrueHeading"])
            < 0.00001
        )
        assert (
            abs(
                expected[desc["filename"]]
                - desc["MAPCompassHeading"]["MagneticHeading"]
            )
            < 0.00001
        )

    # after offset
    x = subprocess.run(
        f"{EXECUTABLE} process {setup_data} --offset_angle=2.5",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    desc_path = setup_data.join("mapillary_image_description.json")
    with open(desc_path) as fp:
        descs = json.load(fp)
    expected = {
        "DSC00001.JPG": 270.89 + 2.5,
        "DSC00497.JPG": 271.27 + 2.5,
        "V0370574.JPG": 1.5,
    }
    for desc in descs:
        assert "filename" in desc
        assert (
            abs(expected[desc["filename"]] - desc["MAPCompassHeading"]["TrueHeading"])
            < 0.00001
        )
        assert (
            abs(
                expected[desc["filename"]]
                - desc["MAPCompassHeading"]["MagneticHeading"]
            )
            < 0.00001
        )


def test_process_boolean_options(
    setup_config: py.path.local, setup_data: py.path.local
):
    os.environ["MAPILLARY_CONFIG_PATH"] = str(setup_config)
    boolean_options = [
        "--add_file_name",
        "--add_import_date",
        "--exclude_import_path",
        "--interpolate_directions",
        "--overwrite_EXIF_direction_tag",
        "--overwrite_EXIF_gps_tag",
        "--overwrite_EXIF_orientation_tag",
        "--overwrite_EXIF_time_tag",
        "--overwrite_all_EXIF_tags",
        "--skip_subfolders",
        "--windows_path",
    ]
    for option in boolean_options:
        x = subprocess.run(
            f"{EXECUTABLE} process {setup_data} {option}",
            shell=True,
        )
        assert x.returncode == 0, x.stderr
    all_options = " ".join(boolean_options)
    x = subprocess.run(
        f"{EXECUTABLE} process {setup_data} {all_options}",
        shell=True,
    )
    assert x.returncode == 0, x.stderr


GPX_CONTENT = """
    <gpx>
    <trk>
        <name>Mapillary GPX</name>
        <trkseg>
            <trkpt lat="0.02" lon="0.01">
            <ele>1</ele>
            <time>2018-06-08T13:23:34.805</time>
            </trkpt>

            <trkpt lat="2.02" lon="0.01">
            <ele>2</ele>
            <time>2018-06-08T13:24:35.809</time>
            </trkpt>

            <trkpt lat="2.02" lon="2.01">
            <ele>4</ele>
            <time>2018-06-08T13:33:36.813</time>
            </trkpt>

            <trkpt lat="4.02" lon="2.01">
            <ele>9</ele>
            <time>2018-06-08T13:58:37.812</time>
            </trkpt>
        </trkseg>
    </trk>
    </gpx>
"""


def find_desc_errors(descs):
    return [desc for desc in descs if "error" in desc]


def filter_out_errors(descs):
    return [desc for desc in descs if "error" not in desc]


def test_geotagging_from_gpx(setup_data: py.path.local):
    gpx_file = setup_data.join("test.gpx")
    desc_path = setup_data.join("mapillary_image_description.json")
    with gpx_file.open("w") as fp:
        fp.write(GPX_CONTENT)
    x = subprocess.run(
        f"{EXECUTABLE} process {setup_data} --geotag_source gpx --geotag_source_path {gpx_file} --skip_process_errors",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    expected_lonlat = {
        # capture_time, lon, lat, elevation
        "DSC00001.JPG": [
            "2018_06_08_13_24_10_000",
            0.01,
            1.1738587633597797,
            1.5769293816798897,
        ],
        "DSC00497.JPG": [
            "2018_06_08_13_32_28_000",
            1.7556100139740183,
            2.02,
            3.7456100139740185,
        ],
    }

    with open(desc_path) as fp:
        descs = json.load(fp)

    assert {"V0370574.JPG"} == {d["filename"] for d in find_desc_errors(descs)}

    for desc in find_desc_errors(descs):
        assert desc.get("error").get("type") == "MapillaryOutsideGPXTrackError"

    for desc in filter_out_errors(descs):
        assert expected_lonlat[desc["filename"]][0] == desc["MAPCaptureTime"]
        assert (
            abs(expected_lonlat[desc["filename"]][1] - desc["MAPLongitude"]) < 0.00001
        )
        assert abs(expected_lonlat[desc["filename"]][2] - desc["MAPLatitude"]) < 0.00001
        assert abs(expected_lonlat[desc["filename"]][3] - desc["MAPAltitude"]) < 0.00001


def test_geotagging_from_gpx_with_offset(setup_data: py.path.local):
    gpx_file = setup_data.join("test.gpx")
    desc_path = setup_data.join("mapillary_image_description.json")
    with gpx_file.open("w") as fp:
        fp.write(GPX_CONTENT)
    x = subprocess.run(
        f"{EXECUTABLE} process {setup_data} --geotag_source gpx --geotag_source_path {gpx_file} --interpolation_offset_time=-20 --skip_process_errors",
        shell=True,
    )
    assert x.returncode == 0, x.stderr

    expected_lonlat = {
        # capture_time, lon, lat, elevation
        "DSC00001.JPG": [
            "2018_06_08_13_23_50_000",
            0.01,
            0.5181640548160776,
            1.2490820274080388,
        ],
        "DSC00497.JPG": [
            "2018_06_08_13_32_08_000",
            1.6816734072206487,
            2.02,
            3.671673407220649,
        ],
    }

    with open(desc_path) as fp:
        descs = json.load(fp)

    assert {"V0370574.JPG"} == {d["filename"] for d in find_desc_errors(descs)}

    for desc in find_desc_errors(descs):
        assert desc.get("error").get("type") == "MapillaryOutsideGPXTrackError"

    for desc in filter_out_errors(descs):
        assert expected_lonlat[desc["filename"]][0] == desc["MAPCaptureTime"]
        assert (
            abs(expected_lonlat[desc["filename"]][1] - desc["MAPLongitude"]) < 0.00001
        )
        assert abs(expected_lonlat[desc["filename"]][2] - desc["MAPLatitude"]) < 0.00001
        assert abs(expected_lonlat[desc["filename"]][3] - desc["MAPAltitude"]) < 0.00001


def test_geotagging_from_gpx_use_gpx_start_time(setup_data: py.path.local):
    gpx_file = setup_data.join("test.gpx")
    with gpx_file.open("w") as fp:
        fp.write(GPX_CONTENT)
    x = subprocess.run(
        f"{EXECUTABLE} process {setup_data} --geotag_source gpx --interpolation_use_gpx_start_time --geotag_source_path {gpx_file} --skip_process_errors",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    expected_lonlat = {
        # capture_time, lon, lat, elevation
        "DSC00001.JPG": ["2018_06_08_13_23_34_805", 0.01, 0.02, 1.0],
        "DSC00497.JPG": [
            "2018_06_08_13_31_52_805",
            1.6255000702397762,
            2.02,
            3.6155000702397766,
        ],
    }
    desc_path = setup_data.join("mapillary_image_description.json")

    with open(desc_path) as fp:
        descs = json.load(fp)

    assert {"V0370574.JPG"} == {d["filename"] for d in find_desc_errors(descs)}

    for desc in find_desc_errors(descs):
        assert desc.get("error").get("type") == "MapillaryOutsideGPXTrackError"

    for desc in filter_out_errors(descs):
        assert expected_lonlat[desc["filename"]][0] == desc["MAPCaptureTime"]
        assert (
            abs(expected_lonlat[desc["filename"]][1] - desc["MAPLongitude"]) < 0.00001
        )
        assert abs(expected_lonlat[desc["filename"]][2] - desc["MAPLatitude"]) < 0.00001
        assert abs(expected_lonlat[desc["filename"]][3] - desc["MAPAltitude"]) < 0.00001


def test_geotagging_from_gpx_use_gpx_start_time_with_offset(setup_data: py.path.local):
    gpx_file = setup_data.join("test.gpx")
    with gpx_file.open("w") as fp:
        fp.write(GPX_CONTENT)
    x = subprocess.run(
        f"{EXECUTABLE} process {setup_data} --geotag_source gpx --interpolation_use_gpx_start_time --geotag_source_path {gpx_file} --interpolation_offset_time=100 --skip_process_errors",
        shell=True,
    )
    assert x.returncode == 0, x.stderr
    expected_lonlat = {
        # capture_time, lon, lat, elevation
        "DSC00001.JPG": [
            "2018_06_08_13_25_14_805",
            0.15416159584772016,
            2.02,
            2.14416159584772,
        ],
        "DSC00497.JPG": [
            "2018_06_08_13_33_32_805",
            1.9951831040066244,
            2.02,
            3.985183104006625,
        ],
    }
    desc_path = setup_data.join("mapillary_image_description.json")
    with open(desc_path) as fp:
        descs = json.load(fp)
    assert {"V0370574.JPG"} == {d["filename"] for d in find_desc_errors(descs)}
    for desc in find_desc_errors(descs):
        assert desc.get("error").get("type") == "MapillaryOutsideGPXTrackError"
    for desc in filter_out_errors(descs):
        assert expected_lonlat[desc["filename"]][0] == desc["MAPCaptureTime"]
        assert (
            abs(expected_lonlat[desc["filename"]][1] - desc["MAPLongitude"]) < 0.00001
        )
        assert abs(expected_lonlat[desc["filename"]][2] - desc["MAPLatitude"]) < 0.00001
        assert abs(expected_lonlat[desc["filename"]][3] - desc["MAPAltitude"]) < 0.00001


def ffmpeg_installed():
    ffmpeg_path = os.getenv("MAPILLARY_FFMPEG_PATH", "ffmpeg")
    try:
        subprocess.run([ffmpeg_path, "-version"])
    except FileNotFoundError:
        return False
    return True


is_ffmpeg_installed = ffmpeg_installed()


def test_sample_video(setup_data: py.path.local):
    if not is_ffmpeg_installed:
        pytest.skip("skip because ffmpeg not installed")

    for input_path in [setup_data, setup_data.join("sample-5s.mp4")]:
        x = subprocess.run(
            f"{EXECUTABLE} sample_video --rerun {input_path}",
            shell=True,
        )
        assert x.returncode != 0, x.stderr
        assert len(setup_data.join("mapillary_sampled_video_frames").listdir()) == 0

        x = subprocess.run(
            f"{EXECUTABLE} sample_video --skip_sample_errors --rerun {input_path}",
            shell=True,
        )
        assert x.returncode == 0, x.stderr
        assert len(setup_data.join("mapillary_sampled_video_frames").listdir()) == 0

        x = subprocess.run(
            f"{EXECUTABLE} sample_video --video_start_time 2021_10_10_10_10_10_123 --rerun {input_path}",
            shell=True,
        )
        assert x.returncode == 0, x.stderr
        sample_path = setup_data.join("mapillary_sampled_video_frames")
        assert len(sample_path.listdir()) == 1
        samples = sample_path.join("sample-5s.mp4").listdir()
        samples.sort()
        times = []
        for s in samples:
            with s.open("rb") as fp:
                tags = exifread.process_file(fp)
                times.append(tags["EXIF DateTimeOriginal"].values)
        assert (
            "2021:10:10 10:10:10.123",
            "2021:10:10 10:10:12.123",
            "2021:10:10 10:10:14.123",
        ) == tuple(times)


def test_video_process(setup_data: py.path.local):
    if not is_ffmpeg_installed:
        pytest.skip("skip because ffmpeg not installed")

    gpx_file = setup_data.join("test.gpx")
    desc_path = setup_data.join("my_samples").join("mapillary_image_description.json")
    with gpx_file.open("w") as fp:
        fp.write(GPX_CONTENT)
    x = subprocess.run(
        f"{EXECUTABLE} video_process --video_start_time 2018_06_08_13_23_34_123 --geotag_source gpx --geotag_source_path {gpx_file} {setup_data} {setup_data.join('my_samples')}",
        shell=True,
    )
    assert x.returncode != 0, x.stderr
    with open(desc_path) as fp:
        descs = json.load(fp)
    assert 1 == len(find_desc_errors(descs))
    assert 2 == len(filter_out_errors(descs))


def test_video_process_multiple_videos(setup_data: py.path.local):
    if not is_ffmpeg_installed:
        pytest.skip("skip because ffmpeg not installed")

    gpx_file = setup_data.join("test.gpx")
    desc_path = setup_data.join("my_samples").join("mapillary_image_description.json")
    sub_folder = setup_data.join("video_sub_folder").mkdir()
    video_path = setup_data.join("sample-5s.mp4")
    video_path.copy(sub_folder)
    with gpx_file.open("w") as fp:
        fp.write(GPX_CONTENT)
    x = subprocess.run(
        f"{EXECUTABLE} video_process --video_start_time 2018_06_08_13_23_34_123 --geotag_source gpx --geotag_source_path {gpx_file} {video_path} {setup_data.join('my_samples')}",
        shell=True,
    )
    assert x.returncode != 0, x.stderr
    with open(desc_path) as fp:
        descs = json.load(fp)
    for d in descs:
        assert d["filename"].startswith("sample-5s.mp4/")
    assert 1 == len(find_desc_errors(descs))
    assert 2 == len(filter_out_errors(descs))


def file_md5sum(path) -> str:
    with open(path, "rb") as fp:
        md5 = hashlib.md5()
        while True:
            buf = fp.read(1024 * 1024 * 32)
            if not buf:
                break
            md5.update(buf)
        return md5.hexdigest()


def test_upload_mp4(
    tmpdir: py.path.local, setup_data: py.path.local, setup_config: py.path.local
):
    os.environ["MAPILLARY_CONFIG_PATH"] = str(setup_config)
    upload_dir = tmpdir.mkdir("mapillary_public_uploads")
    os.environ["MAPILLARY_UPLOAD_PATH"] = str(upload_dir)
    video_path = setup_data.join("sample-5s.mp4")
    x = subprocess.run(
        f"{EXECUTABLE} upload {video_path} --dry_run --user_name={USERNAME}",
        shell=True,
    )
    assert x.returncode == 9, x.stderr

    # TODO: disable because we don't have blackvue for testing yet
    # assert 1 == len(upload_dir.listdir())
    # assert {"mly_tools_8cd0e9af15f4baaafe9dfe98ace8b886.mp4"} == {
    #     os.path.basename(f) for f in upload_dir.listdir()
    # }
    # md5sum = file_md5sum(video_path)
    # assert {md5sum} == {file_md5sum(f) for f in upload_dir.listdir()}
