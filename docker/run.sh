#!/bin/sh

docker run \
       --platform linux/amd64 \
       --tty \
       --interactive \
       --publish 7070:7070 \
       --volume .:/work/code \
       --volume $HOME/Code/RestoredCDC/Restore-CDC-WARC/data:/work/data \
       --workdir /work/code \
       serve-cdc-warc
