#!/bin/sh
TEMPDIR=`mktemp -d`
CFGFILE=cinder.conf.sample
tools/conf/generate_sample.sh -o $TEMPDIR
if ! diff $TEMPDIR/$CFGFILE etc/cinder/$CFGFILE
then
    echo "E: cinder.conf.sample is not up to date, please run tools/conf/generate_sample.sh in venv"
    echo "E: e.g. \$ source .venv/bin/activate; tools/conf/generate_sample.sh"
    rm -rf $TEMPDIR
    exit 42
fi
rm -rf $TEMPDIR
