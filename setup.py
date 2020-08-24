#!/usr/bin/env python
from setuptools import setup

setup(name='mapillary_tools',
      version='0.5.1p3',
      description='Mapillary Image/Video Import Pipeline',
      url='https://github.com/mapillary/mapillary_tools',
      author='Mapillary',
      license='BSD',
      python_requires='>=3.8.0, ',
      packages=['mapillary_tools', 'mapillary_tools.commands','mapillary_tools.camera_support'],
      scripts=['bin/mapillary_tools'],
      install_requires=[
          'exifread',
          'gpxpy',
          'Pillow',
          'python-dateutil',
          'pymp4',
          'pynmea2',
          'pytest',
          'tqdm',
          'requests==2.20.0',
          'pytz',
          'piexif',
      ])
