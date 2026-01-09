# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from multiprocessing import freeze_support

from mapillary_tools.commands.__main__ import main

if __name__ == "__main__":
    # fix multiprocessing spawn: https://github.com/pyinstaller/pyinstaller/issues/4865
    freeze_support()
    main()
