#!/usr/bin/env python
import os
from setuptools import setup

here = os.path.abspath(os.path.dirname(__file__))


def read_requirements():
    with open("requirements.txt") as fp:
        return [row.strip() for row in fp if row.strip()]


about = {}
with open(os.path.join(here, "mapillary_tools", "__init__.py"), "r") as f:
    exec(f.read(), about)


setup(
    name="mapillary_tools",
    version=about["VERSION"],
    description="Mapillary Image/Video Import Pipeline",
    url="https://github.com/mapillary/mapillary_tools",
    author="Mapillary",
    license="BSD",
    python_requires=">=3.6",
    packages=["mapillary_tools", "mapillary_tools.commands", "mapillary_tools.geotag"],
    entry_points="""
      [console_scripts]
      mapillary_tools=mapillary_tools.commands.__main__:main
      """,
    install_requires=read_requirements(),
)
