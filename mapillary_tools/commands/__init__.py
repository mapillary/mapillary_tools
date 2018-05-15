from . import extract_user_data
from . import extract_geotag_data
from . import extract_import_meta_data
from . import extract_sequence_data
from . import extract_upload_params
from . import exif_insert
#from . import upload
#from . import process
#from . import process_and_upload

mapillary_tools_commands = [
    extract_user_data,
    extract_geotag_data,
    extract_import_meta_data,
    extract_sequence_data,
    extract_upload_params,
    exif_insert]
'''
    exif_insert,
    upload,
    process,
    process_and_upload
]
'''