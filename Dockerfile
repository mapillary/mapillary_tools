FROM ubuntu:20.04
RUN apt update -y && apt install -y python3 python3-pip git
RUN python3 -m pip install --upgrade git+https://github.com/mapillary/mapillary_tools
