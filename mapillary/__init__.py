#!/usr/bin/python
# coding: utf8

"""
Mapillary: Useful tools
=======================
Making the Upload with Authentication process easier with only Email & Password authentication.

Install
-------
$ python setup.py install

How to use
----------
$ upload_with_authentication <File Path> -e your@email.com -p Password

Using Environment Variables
---------------------------
Connect the the following URL for Hashes
http://api.mapillary.com/v1/u/uploadhashes

**Exporting env Variables**

$ export $MAPILLARY_PERMISSION_HASH=<permission_hash>
$ export $MAPILLARY_SIGNATURE_HASH=<signature_hash>
$ upload_with_authentication <File Path>
"""

# CLI
import upload_with_authentication