FROM ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt update -y && apt install -y python3 python3-pip git && apt install -y --no-install-recommends ffmpeg

RUN python3 -m pip install --upgrade git+https://github.com/mapillary/mapillary_tools
