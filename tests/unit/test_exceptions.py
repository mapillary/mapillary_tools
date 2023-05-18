import json
from pathlib import Path

from mapillary_tools import exceptions, types


def test_all():
    all_excs = [
        getattr(exceptions, ex)
        for ex in dir(exceptions)
        if ex.startswith("Mapillary") and ex.endswith("Error")
    ]

    all_desc_excs = [
        exc
        for exc in all_excs
        if issubclass(exc, exceptions._MapillaryDescriptionError)
    ]

    for exc in all_desc_excs:
        if exc is exceptions.MapillaryOutsideGPXTrackError:
            e = exc("hello", "world", "hey", "aa")
        elif exc is exceptions.MapillaryDuplicationError:
            e = exc("hello", {}, 1, float("inf"))
        elif exc is exceptions.MapillaryUploadedAlreadyError:
            e = exc("world", {})
        else:
            e = exc("hello")
        # should not raise
        json.dumps(
            types._describe_error_desc(e, Path("test.jpg"), types.FileType.IMAGE)
        )
