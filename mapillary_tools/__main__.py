import sys
import argparse
from . import commands, VERSION


def main():
    advanced = "--advanced" in sys.argv
    version = "--version" in sys.argv
    full_help = "--full_help" in sys.argv

    if version:
        print("")
        print("Mapillary tools version : " + VERSION)
        print("")
        if len(sys.argv) < 3:
            sys.exit()

    # Create the top-level parser
    parser = argparse.ArgumentParser(
        "Mapillary import tool",
        usage="see -h for available tools and corresponding arguments, add --advanced to see additional advanced tools and/or arguments and --version to see version.",
    )
    parser.add_argument(
        "--advanced",
        help="Use the tools under an advanced level with additional arguments and tools available.",
        action="store_true",
        required=False,
        default=False,
    )
    parser.add_argument(
        "--version",
        help="Print mapillary tools version.",
        action="store_true",
        required=False,
        default=False,
    )
    parser.add_argument(
        "--full_help",
        help="Print full help for all the available commands and their arguments.",
        action="store_true",
        required=False,
        default=False,
    )

    subparsers = parser.add_subparsers(
        help="Please choose one of the available tools", dest="tool", metavar="tool"
    )

    # Load the subcommands
    advanced_commands = [
        module.Command() for module in commands.mapillary_tools_advanced_commands
    ]
    basic_commands = [module.Command() for module in commands.mapillary_tools_commands]

    # Create one subparser for each subcommand
    all_commands = basic_commands
    if advanced:
        all_commands += advanced_commands

    for command in all_commands:
        subparser = subparsers.add_parser(command.name, help=command.help)
        commands.add_general_arguments(subparser, command.name)
        command.add_basic_arguments(subparser)
        if advanced:
            command.add_advanced_arguments(subparser)

    if full_help:
        subparsers_actions = [
            action
            for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        ]
        for subparsers_action in subparsers_actions:
            for choice, subparser in subparsers_action.choices.items():
                print(f"Subcommand '{choice}'")
                print(subparser.format_help())

    args = parser.parse_args()

    args_command = vars(args)["tool"]
    del vars(args)["tool"]
    if "advanced" in vars(args):
        del vars(args)["advanced"]
    if "version" in vars(args):
        del vars(args)["version"]
    if "full_help" in vars(args):
        del vars(args)["full_help"]

    # Run the selected subcommand if unit command, or in case of batch
    # command, run several unit commands
    for command in all_commands:
        if args_command == command.name:
            command.run(args)


if __name__ == "__main__":
    main()
