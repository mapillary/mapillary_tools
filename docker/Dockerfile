FROM ubuntu:16.04

# SETUP
RUN \
    apt-get -qq update && \
    apt-get -yqq install \
        git \
        python-pip && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

RUN \
    pip install --upgrade pip

COPY . /mapillary_source/

WORKDIR /mapillary_source
RUN pip install -r requirements.txt

ARG MAPILLARY_GITHUB_TOKEN
RUN apt update -y && apt install -y python3 python3-pip git && echo "$(python3 --version) installed!"
RUN pip3 install --upgrade pip
RUN pip3 install git+https://$MAPILLARY_GITHUB_TOKEN:x-oauth-basic@github.com/mapillary/mapillary_toolchain.git && \
    MTC_PATH=$(python3 -c 'import mapillary_toolchain as m; print(m.__path__[0])') && \
    ls -l "${MTC_PATH}/bin/mtc_init.sh" /usr/local/bin && \
    ln -s "${MTC_PATH}/bin/mtc_init.sh" /usr/local/bin/mtc_init

