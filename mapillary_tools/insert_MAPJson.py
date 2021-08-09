import typing as T
import json
import logging
import os
import uuid

from tqdm import tqdm

from . import image_log, types, processing
from .geojson import desc_to_feature_collection

LOG = logging.getLogger()


def get_final_mapillary_image_description(
    image: str,
) -> T.Optional[T.Tuple[types.Status, T.Mapping]]:
    ret = image_log.read_process_data_from_memory(image, "geotag_process")
    if ret is None:
        return None

    status, geotag_desc = ret
    if status != "success":
        return status, geotag_desc

    ret = image_log.read_process_data_from_memory(image, "sequence_process")
    if ret is None:
        return None

    status, sequence_desc = ret
    if status != "success":
        return status, sequence_desc

    description: dict = {}
    description.update(T.cast(dict, geotag_desc))
    # sequence desc overrides the image desc
    description.update(T.cast(dict, sequence_desc))

    ret = image_log.read_process_data_from_memory(image, "import_meta_data_process")
    if ret is not None:
        status, meta_desc = ret
        if status == "success":
            description.update(T.cast(dict, meta_desc))

    description["MAPPhotoUUID"] = str(uuid.uuid4())

    return status, T.cast(types.FinalImageDescription, description)


def insert_MAPJson(
    import_path,
    rerun=False,
    skip_subfolders=False,
    overwrite_all_EXIF_tags=False,
    overwrite_EXIF_time_tag=False,
    overwrite_EXIF_gps_tag=False,
    overwrite_EXIF_direction_tag=False,
    overwrite_EXIF_orientation_tag=False,
    write_geojson: str = None,
):

    # basic check for all
    if not import_path or not os.path.isdir(import_path):
        raise RuntimeError(
            f"Error, import directory {import_path} does not exist, exiting..."
        )

    images = image_log.get_total_file_list(import_path, skip_subfolders=skip_subfolders)

    if not images:
        print("No images to run process finalization")
        return

    all_desc = []
    for image in tqdm(images, unit="files", desc="Processing image description"):
        ret = get_final_mapillary_image_description(image)
        if ret is None:
            continue

        status, desc = ret

        if status == "success":
            try:
                processing.overwrite_exif_tags(
                    image,
                    T.cast(types.FinalImageDescription, desc),
                    overwrite_all_EXIF_tags,
                    overwrite_EXIF_time_tag,
                    overwrite_EXIF_gps_tag,
                    overwrite_EXIF_direction_tag,
                    overwrite_EXIF_orientation_tag,
                )
            except Exception:
                LOG.warning(f"Failed to overwrite EXIF", exc_info=True)

            all_desc.append(T.cast(types.FinalImageDescription, desc))

        image_log.create_and_log_process(
            image,
            "mapillary_image_description",
            status,
            desc,
        )

    if write_geojson is not None:
        if write_geojson == "-":
            print(json.dumps(desc_to_feature_collection(all_desc), indent=4))
        else:
            with open(write_geojson, "w") as fp:
                json.dump(desc_to_feature_collection(all_desc), fp, indent=4)
