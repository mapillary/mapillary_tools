
from mapillary_tools.edit_config import (
    add_user_auth_arguments,
    add_edit_config_arguments,
    edit_config)


class Command:
    name = 'authenticate'
    help = "Helper tool : (Re)run authentication."

    def add_basic_arguments(self, parser):
        add_user_auth_arguments(parser)
        add_edit_config_arguments(parser)

    def add_advanced_arguments(self, parser):
        pass

    def run(self, args):
        edit_config(**vars(args))
