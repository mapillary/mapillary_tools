#!/usr/bin/env python
import os

from setuptools import setup

here = os.path.abspath(os.path.dirname(__file__))


def read_requirements():
    import ssl

    requires = []

    # Workaround for python3.9 on macOS which is compiled with LibreSSL
    # See https://github.com/urllib3/urllib3/issues/3020
    if not ssl.OPENSSL_VERSION.startswith("OpenSSL "):
        requires.append("urllib3<2.0.0")

    with open("requirements.txt") as fp:
        requires.extend([row.strip() for row in fp if row.strip()])

    return requires


about = {}
with open(os.path.join(here, "mapillary_tools", "__init__.py"), "r") as f:
    exec(f.read(), about)


def readme():
    with open("README.md") as f:
        return f.read()


setup(
    name="mapillary_tools",
    version=about["VERSION"],
    description="Mapillary Image/Video Import Pipeline",
    long_description=readme(),
    long_description_content_type="text/markdown",
    url="https://github.com/mapillary/mapillary_tools",
    author="Mapillary",
    license="BSD",
    python_requires=">=3.8",
    packages=[
        "mapillary_tools",
        "mapillary_tools.camm",
        "mapillary_tools.commands",
        "mapillary_tools.geotag",
        "mapillary_tools.mp4",
        "mapillary_tools.video_data_extraction",
        "mapillary_tools.video_data_extraction.extractors",
    ],
    entry_points="""
      [console_scripts]
      mapillary_tools=mapillary_tools.commands.__main__:main
      """,
    install_requires=read_requirements(),
)
