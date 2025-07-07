import datetime
import json
import sys
import typing as T

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

import gpxpy
import gpxpy.gpx

from .. import geo, types

from ..telemetry import CAMMGPSPoint, GPSPoint
from ..types import (
    BaseSerializer,
    ErrorMetadata,
    ImageMetadata,
    MetadataOrError,
    VideoMetadata,
)
from .description import DescriptionJSONSerializer


class GPXSerializer(BaseSerializer):
    @override
    @classmethod
    def serialize(cls, metadatas: T.Sequence[MetadataOrError]) -> bytes:
        gpx = cls.as_gpx(metadatas)
        return gpx.to_xml().encode("utf-8")

    @classmethod
    def as_gpx(cls, metadatas: T.Sequence[MetadataOrError]) -> gpxpy.gpx.GPX:
        gpx = gpxpy.gpx.GPX()

        error_metadatas = []
        image_metadatas = []
        video_metadatas = []

        for metadata in metadatas:
            if isinstance(metadata, ErrorMetadata):
                error_metadatas.append(metadata)
            elif isinstance(metadata, ImageMetadata):
                image_metadatas.append(metadata)
            elif isinstance(metadata, VideoMetadata):
                video_metadatas.append(metadata)

        for metadata in error_metadatas:
            gpx_track = gpxpy.gpx.GPXTrack()
            gpx_track.name = str(metadata.filename)
            gpx_track.description = cls._build_gpx_description(metadata, ["filename"])
            gpx.tracks.append(gpx_track)

        sequences = types.group_and_sort_images(image_metadatas)
        for sequence_uuid, sequence in sequences.items():
            gpx.tracks.append(cls.image_sequence_as_gpx_track(sequence_uuid, sequence))

        for metadata in video_metadatas:
            gpx.tracks.append(cls.as_gpx_track(metadata))

        return gpx

    @classmethod
    def as_gpx_point(cls, point: geo.Point) -> gpxpy.gpx.GPXTrackPoint:
        gpx_point = gpxpy.gpx.GPXTrackPoint(
            latitude=point.lat,
            longitude=point.lon,
            elevation=point.alt,
            time=datetime.datetime.fromtimestamp(point.time, datetime.timezone.utc),
        )

        if isinstance(point, types.ImageMetadata):
            gpx_point.name = point.filename.name
        elif isinstance(point, CAMMGPSPoint):
            gpx_point.time = datetime.datetime.fromtimestamp(
                point.time_gps_epoch, datetime.timezone.utc
            )
        elif isinstance(point, GPSPoint):
            if point.epoch_time is not None:
                gpx_point.time = datetime.datetime.fromtimestamp(
                    point.epoch_time, datetime.timezone.utc
                )

        return gpx_point

    @classmethod
    def as_gpx_track(cls, metadata: VideoMetadata) -> gpxpy.gpx.GPXTrack:
        gpx_segment = gpxpy.gpx.GPXTrackSegment()
        for point in metadata.points:
            gpx_point = cls.as_gpx_point(point)
            gpx_segment.points.append(gpx_point)
        gpx_track = gpxpy.gpx.GPXTrack()
        gpx_track.name = str(metadata.filename)
        gpx_track.description = cls._build_gpx_description(
            metadata, ["filename", "MAPGPSTrack"]
        )
        gpx_track.segments.append(gpx_segment)
        return gpx_track

    @classmethod
    def image_sequence_as_gpx_track(
        cls, sequence_uuid: str, sequence: T.Sequence[ImageMetadata]
    ) -> gpxpy.gpx.GPXTrack:
        gpx_segment = gpxpy.gpx.GPXTrackSegment()
        for metadata in sequence:
            gpx_point = cls.as_gpx_point(metadata)
            gpx_segment.points.append(gpx_point)
        gpx_track = gpxpy.gpx.GPXTrack()
        gpx_track.name = sequence_uuid
        gpx_track.description = cls._build_gpx_description(
            metadata,
            [
                "filename",
                "MAPLongitude",
                "MAPLatitude",
                "MAPCaptureTime",
                "MAPAltitude",
            ],
        )
        gpx_track.segments.append(gpx_segment)
        return gpx_track

    @classmethod
    def _build_gpx_description(
        cls, metadata: MetadataOrError, excluded_properties: T.Sequence[str]
    ) -> str:
        desc = T.cast(T.Dict, DescriptionJSONSerializer.as_desc(metadata))
        for prop in excluded_properties:
            desc.pop(prop, None)
        return json.dumps(desc, sort_keys=True, separators=(",", ":"))
