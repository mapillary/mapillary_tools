#!/usr/bin/env python
from distutils.core import setup

setup(name='mapillary_tools',
      version='0.0',
      description='Mapillary Image/Video Import Pipeline',
      url='https://github.com/mapillary/mapillary_tools',
      author='Mapillary',
      license='BSD',
      packages=['mapillary_tools', 'mapillary_tools.commands'],
      scripts=['bin/mapillary_import'])
