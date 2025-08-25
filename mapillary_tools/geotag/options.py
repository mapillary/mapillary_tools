from __future__ import annotations

import dataclasses
import enum
import json
import typing as T
from pathlib import Path

import jsonschema

from .. import types


class SourceType(enum.Enum):
    NATIVE = "native"
    GPX = "gpx"
    NMEA = "nmea"
    EXIFTOOL_XML = "exiftool_xml"
    EXIFTOOL_RUNTIME = "exiftool_runtime"

    # Legacy source types for images
    GOPRO = "gopro"
    BLACKVUE = "blackvue"
    CAMM = "camm"
    EXIF = "exif"


SOURCE_TYPE_ALIAS: dict[str, SourceType] = {
    "blackvue_videos": SourceType.BLACKVUE,
    "gopro_videos": SourceType.GOPRO,
    "exiftool": SourceType.EXIFTOOL_RUNTIME,
}


@dataclasses.dataclass
class SourceOption:
    # Type of the source
    source: SourceType

    # Filter by these filetypes
    filetypes: set[types.FileType] | None = None

    num_processes: int | None = None

    source_path: SourcePathOption | None = None

    interpolation: InterpolationOption | None = None

    @classmethod
    def from_dict(cls, data: dict[str, T.Any]) -> SourceOption:
        validate_option(data)

        kwargs: dict[str, T.Any] = {}
        for k, v in data.items():
            # None values are considered as absent and should be ignored
            if v is None:
                continue
            if k == "source":
                kwargs[k] = SourceType(SOURCE_TYPE_ALIAS.get(v, v))
            elif k == "filetypes":
                kwargs[k] = {types.FileType(t) for t in v}
            elif k == "source_path":
                kwargs.setdefault(
                    "source_path", SourcePathOption(source_path=Path(v))
                ).sourthe_path = Path(v)
            elif k == "pattern":
                kwargs.setdefault(
                    "source_path", SourcePathOption(pattern=v)
                ).pattern = v
            elif k == "interpolation_offset_time":
                kwargs.setdefault(
                    "interpolation", InterpolationOption()
                ).offset_time = v
            elif k == "interpolation_use_gpx_start_time":
                kwargs.setdefault(
                    "interpolation", InterpolationOption()
                ).use_gpx_start_time = v

        return cls(**kwargs)


@dataclasses.dataclass
class SourcePathOption:
    pattern: str | None = None
    source_path: Path | None = None

    def __post_init__(self):
        if self.source_path is None and self.pattern is None:
            raise ValueError("Either pattern or source_path must be provided")

    def resolve(self, path: Path) -> Path:
        """
        Resolve the source path or pattern against the given path.

        Examples:
            >>> from pathlib import Path
            >>> opt = SourcePathOption(source_path=Path("/foo/bar.mp4"))
            >>> opt.resolve(Path("/baz/qux.mp4"))
            PosixPath('/foo/bar.mp4')

            >>> opt = SourcePathOption(pattern="videos/%g_sub%e")
            >>> opt.resolve(Path("/data/video1.mp4"))
            PosixPath('/data/videos/video1_sub.mp4')

            >>> opt = SourcePathOption(pattern="/abs/path/%f")
            >>> opt.resolve(Path("/tmp/abc.mov"))
            PosixPath('/abs/path/abc.mov')
        """

        if self.source_path is not None:
            return self.source_path

        assert self.pattern is not None, (
            "either pattern or source_path must be provided"
        )

        # %f: the full video filename (foo.mp4)
        # %g: the video filename without extension (foo)
        # %e: the video filename extension (.mp4)
        replaced = Path(
            self.pattern.replace("%f", path.name)
            .replace("%g", path.stem)
            .replace("%e", path.suffix)
        )

        abs_path = (
            replaced
            if replaced.is_absolute()
            else Path.joinpath(path.parent.resolve(), replaced)
        ).resolve()

        return abs_path


@dataclasses.dataclass
class InterpolationOption:
    offset_time: float = 0.0
    use_gpx_start_time: bool = False


SourceOptionSchema = {
    "type": "object",
    "properties": {
        "source": {
            "type": "string",
            "enum": [s.value for s in SourceType] + list(SOURCE_TYPE_ALIAS.keys()),
        },
        "filetypes": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [t.value for t in types.FileType],
            },
        },
        "source_path": {
            "type": "string",
        },
        "pattern": {
            "type": "string",
        },
        "num_processes": {
            "type": "integer",
        },
        "interpolation_offset_time": {
            "type": "number",
        },
        "interpolation_use_gpx_start_time": {
            "type": "boolean",
        },
    },
    "required": ["source"],
    "additionalProperties": False,
}


SourceOptionSchemaValidator = jsonschema.Draft202012Validator(SourceOptionSchema)


def validate_option(instance):
    SourceOptionSchemaValidator.validate(instance=instance)


if __name__ == "__main__":
    # python -m mapillary_tools.geotag.options > schema/geotag_source_option.json
    print(json.dumps(SourceOptionSchema, indent=4))
