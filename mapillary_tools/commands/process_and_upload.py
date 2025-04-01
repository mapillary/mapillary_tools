import inspect

from ..authenticate import fetch_user_items

from .process import Command as ProcessCommand
from .upload import Command as UploadCommand


class Command:
    name = "process_and_upload"
    help = "process images or videos and upload to Mapillary"

    def add_basic_arguments(self, parser):
        ProcessCommand().add_basic_arguments(parser)
        UploadCommand().add_basic_arguments(parser)

    def run(self, vars_args: dict):
        if vars_args.get("desc_path") is None:
            # \x00 is a special path similiar to /dev/null
            # it tells process command do not write anything
            vars_args["desc_path"] = "\x00"

        if "user_items" not in vars_args:
            vars_args["user_items"] = fetch_user_items(
                **{
                    k: v
                    for k, v in vars_args.items()
                    if k in inspect.getfullargspec(fetch_user_items).args
                }
            )

        ProcessCommand().run(vars_args)
        UploadCommand().run(vars_args)
