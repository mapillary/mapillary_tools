#!/usr/bin/env python
from distutils.core import setup

setup(name='mapillary_tools',
      version='0.0.2',
      description='Mapillary Image/Video Import Pipeline',
      url='https://github.com/mapillary/mapillary_tools',
      author='Mapillary',
      license='BSD',
      packages=['mapillary_tools', 'mapillary_tools.commands'],
      scripts=['bin/mapillary_tools'],
      install_requires=[
          'exifread==1.4.1',
          'gpxpy==0.9.8',
          'Pillow==2.9.0',
          'python-dateutil==2.7.3',
          'pynmea2==1.12.0',
          'pytest==3.2.3'
      ])
