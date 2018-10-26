#!/usr/bin/env python
from setuptools import setup

setup(name='mapillary_tools',
      version='0.3.0',
      description='Mapillary Image/Video Import Pipeline',
      url='https://github.com/mapillary/mapillary_tools',
      author='Mapillary',
      license='BSD',
      python_requires='>=2.7.0,<3.0.0',
      packages=['mapillary_tools', 'mapillary_tools.commands'],
      scripts=['bin/mapillary_tools'],
      install_requires=[
          'exifread==2.1.2',
          'gpxpy==0.9.8',
          'Pillow==2.9.0',
          'python-dateutil==2.7.3',
          'pymp4==1.1.0',
          'pynmea2==1.12.0',
          'pytest==3.2.3',
          'tqdm==2.2.4'
      ])
