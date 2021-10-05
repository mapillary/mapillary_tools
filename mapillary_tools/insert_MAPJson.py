import typing as T
import json
import logging
import os
import uuid

from tqdm import tqdm

from . import image_log, types, processing

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
    skip_subfolders=False,
    overwrite_all_EXIF_tags=False,
    overwrite_EXIF_time_tag=False,
    overwrite_EXIF_gps_tag=False,
    overwrite_EXIF_direction_tag=False,
    overwrite_EXIF_orientation_tag=False,
    desc_path: str = None,
):
    # basic check for all
    if not import_path or not os.path.isdir(import_path):
        raise RuntimeError(
            f"Error, import directory {import_path} does not exist, exiting..."
        )

    if desc_path is None:
        desc_path = os.path.join(import_path, "mapillary_image_description.json")

    images = image_log.get_total_file_list(import_path, skip_subfolders=skip_subfolders)

    all_desc: T.List[types.FinalImageDescriptionOrError] = []
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

        relpath = os.path.relpath(image, import_path)
        if status == "success":
            all_desc.append(
                T.cast(types.FinalImageDescription, {**desc, "filename": relpath})
            )
        else:
            all_desc.append(
                T.cast(
                    types.FinalImageDescriptionError,
                    {"error": desc, "filename": relpath},
                )
            )

    if desc_path == "-":
        print(json.dumps(all_desc, indent=4))
    else:
        with open(desc_path, "w") as fp:
            json.dump(all_desc, fp, indent=4)
