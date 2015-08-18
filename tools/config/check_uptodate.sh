#!/usr/bin/env bash

CHECKONLY=0
if [ "$1" == "--checkonly" ]; then
    CHECKONLY=1
fi

PROJECT_NAME=${PROJECT_NAME:-cinder}
CFGFILE_NAME=${PROJECT_NAME}.conf.sample


TEMPDIR=`mktemp -d /tmp/${PROJECT_NAME}.XXXXXX`
trap "rm -rf $TEMPDIR" EXIT

tools/config/generate_sample.sh -b ./ -p ${PROJECT_NAME} -o ${TEMPDIR}

# generate_sample.sh may return 0 even when it fails.

if [ $CHECKONLY -eq 1 ]; then
    # Check whether something was generated.
    if [ ! -s ${TEMPDIR}/${CFGFILE_NAME} ]; then
        echo "Failed to generate ${CFGFILE_NAME}."
        exit 1
    fi
else
    if [ -e etc/${PROJECT_NAME}/${CFGFILE_NAME} ]; then
        CFGFILE=etc/${PROJECT_NAME}/${CFGFILE_NAME}
    elif [ -e etc/${CFGFILE_NAME} ]; then
        CFGFILE=etc/${CFGFILE_NAME}
    else
        echo "${0##*/}: can not find config file"
        exit 1
    fi

    if ! diff -u ${TEMPDIR}/${CFGFILE_NAME} ${CFGFILE}
    then
        echo "${0##*/}: ${PROJECT_NAME}.conf.sample is not up to date."
        echo "${0##*/}: Please run ${0%%${0##*/}}generate_sample.sh from within a VENV."
        echo "  \'source .venv/bin/activate; generate_sample.sh\'"
        echo "OR simply run tox genconfig"
        echo "  \'tox -egenconfig\'"
        exit 1
    fi
fi
