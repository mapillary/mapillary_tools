# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import pytest
from mapillary_tools import exceptions, geo
from mapillary_tools.geotag.geotag_images_from_gpx import check_within_track


def test_a_time_past_year_9999_is_outside_the_track():
    """
    A time offset can move an image past year 9999. Writing its time into the
    error stopped the run, rather than fail the image
    """
    track = [geo.Point(time=t, lat=0, lon=0, alt=None, angle=None) for t in (10, 20)]

    with pytest.raises(exceptions.MapillaryOutsideGPXTrackError) as info:
        check_within_track(3e11, track)

    assert info.value.image_time == "300000000000.0"
    assert info.value.gpx_end_time == "1970_01_01_00_00_20_000"
