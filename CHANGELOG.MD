## 0.0.0 (2018-05-30)


### Breaking changes

* The library has been rewritten for this initial release. The library usage is different from before. Refer to the documentation in the [README](https://github.com/mapillary/mapillary_tools/blob/mapillary_tools_v2/README.md) for instructions on requirement installation and usage. Due to an incompatible logging procedure, previous tools need to be used to finish uploading any sequences that were partially uploaded with the previous tools.

### Features and improvements
* Improved authentication procedure
* Improved user interface with only one executable that can run several basic tools with basic arguments, as well as advanced tools and/or advanced arguments
* Improved logging procedure
* Simpler installation with pip
* Modules can be imported in Python to enable easier development of custom process and/or upload scripts

### Bug fixes
* Inadequate README [#219](https://github.com/mapillary/mapillary_tools/issues/219), [#180](https://github.com/mapillary/mapillary_tools/issues/180), [#159](https://github.com/mapillary/mapillary_tools/issues/159), [#229](https://github.com/mapillary/mapillary_tools/issues/229), [#226](https://github.com/mapillary/mapillary_tools/issues/226), [#157](https://github.com/mapillary/mapillary_tools/issues/157)
* Removal of obsolete scripts [#162](https://github.com/mapillary/mapillary_tools/issues/162)
* Inadequate logging [#63](https://github.com/mapillary/mapillary_tools/issues/63)


## 0.0.1 (2018-06-04)

### Bug fixes
* Store the subsecond estimations done in sequence processing in case of identical timestamps


## 0.0.2 (2018-06-20)

### Bug fixes
* Update the timestamps list in case duplicates are flagged


## 0.1.0 (2018-06-12)

### Breaking changes

* Logging was modified to store log files in a hidden directory where the image is located and not in the import path.

### Features and improvements
* DONE file is created in the import path and not where the tools are being run from.
* exifread version requirement upgraded to resolve installation issues
* support geotagging from a csv file
* support various interpolations
* support re-authentication as a command
* support option to keep the original images intact
* print out version
* increase the amount of information printed out without the verbose flag.

