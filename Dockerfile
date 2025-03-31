# To create the docker image:
#
#   docker build -t serve-cdc-warc .
#
# Run it while sharing the repo and data (adjust the source directory
# for /work/data in that script to your personal setup):
#
#   docker/run.sh
#
FROM --platform=linux/amd64 ubuntu

RUN apt update
RUN apt install -y less python3 python3-venv python3-pip
RUN mkdir /work
RUN python3 -m venv /work
RUN --mount=type=bind,source=requirements.txt,target=requirements.txt \
    . /work/bin/activate && pip3 install -r requirements.txt

COPY docker/init.sh /
CMD ["/init.sh"]
