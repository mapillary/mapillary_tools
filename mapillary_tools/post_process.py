import json
import os


def post_process(import_path, desc_path: str = None):
    # basic check for all
    if not import_path or not os.path.isdir(import_path):
        raise RuntimeError(
            f"Error, import directory {import_path} does not exist, exiting..."
        )

    if desc_path is None:
        desc_path = os.path.join(import_path, "mapillary_image_description.json")

    with open(desc_path, "r") as fp:
        descs = json.load(fp)

    summary = {
        "total_images": len(descs),
        "processed_images": len([desc for desc in descs if "error" not in desc]),
        "failed_images": len([desc for desc in descs if "error" in desc]),
    }

    print(json.dumps(summary, indent=4))
