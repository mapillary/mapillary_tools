# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the BSD license found in the
# LICENSE file in the root directory of this source tree.

import json
import sys

from mapillary_tools import process_sequence_properties


def main():
    descs = json.load(sys.stdin)
    processed_descs = process_sequence_properties.process_sequence_properties(descs)
    print(json.dumps(processed_descs))


if __name__ == "__main__":
    main()
