from multiprocessing import freeze_support

from mapillary_tools.commands.__main__ import main

if __name__ == "__main__":
    # fix multiprocessing spawn: https://github.com/pyinstaller/pyinstaller/issues/4865
    freeze_support()
    main()
