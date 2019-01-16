from mapillary_tools.uploader import send_videos_for_processing

class Command:
    name = 'send_videos_for_processing'
    help = "Helper tool : (Re)run authentication."

    def add_basic_arguments(self, parser):
        parser.add_argument(
            '--config_file', help='Full path to the config file to be edited. Default is ~/.config/mapillary/config', default=None, required=False)
        parser.add_argument("--user_name", help="Mapillary user name",
                            default=None, required=False)
        parser.add_argument(
            "--user_email", help="user email, used to create Mapillary account", default=None, required=False)
        parser.add_argument(
            "--user_password", help="password associated with the Mapillary user account", default=None, required=False)
        parser.add_argument(
            '--user_key', help='Manually specify user key', default=False, required=False)
        parser.add_argument(
            '--api_version', help='Choose which Mapillary API version to use', default=1.0, required=False)

    def add_advanced_arguments(self, parser):
        pass

    def run(self, args):
        send_files_for_processing(**vars(args))
