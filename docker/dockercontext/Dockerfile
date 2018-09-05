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
COPY docker/dockercontext/mapillary/ /mapillary
ENV PATH="/mapillary:${PATH}"
