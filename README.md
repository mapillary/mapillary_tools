Mapillary: Useful tools
=======================

Install
-------

```bash
$ git clone https://github.com/mapillary/mapillary_tools.git
$ cd mapillary_tools
$ python setup.py install
```

How to use
----------

```bash
$ upload_with_authentication <File Path> -e your@email.com -p Password
```

Using Environment Variables
---------------------------
Connect the the following URL for Hashes

- http://api.mapillary.com/v1/u/uploadhashes

**Exporting env Variables**

```bash
    $ export $MAPILLARY_PERMISSION_HASH=<permission_hash>
    $ export $MAPILLARY_SIGNATURE_HASH=<signature_hash>
    $ upload_with_authentication <File Path>
```