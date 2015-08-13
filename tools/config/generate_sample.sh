#!/usr/bin/env bash

# Generate sample configuration for your project.
#
# Aside from the command line flags, it also respects a config file which
# should be named oslo.config.generator.rc and be placed in the same directory.
#
# You can then export the following variables:
# CINDER_CONFIG_GENERATOR_EXTRA_MODULES: list of modules to interrogate for options.
# CINDER_CONFIG_GENERATOR_EXTRA_LIBRARIES: list of libraries to discover.
# CINDER_CONFIG_GENERATOR_EXCLUDED_FILES: list of files to remove from automatic listing.

BASEDIR=${BASEDIR:-`pwd`}

print_error ()
{
    echo -en "\n\n##########################################################"
    echo -en "\nERROR: ${0} was not called from tox."
    echo -en "\n        Execute 'tox -e genconfig' for cinder.conf.sample"
    echo -en "\n        generation."
    echo -en "\n##########################################################\n\n"
}

if [ -z ${1} ] ; then
    print_error
    exit 1
fi

if [ ${1} != "from_tox" ] ; then
    print_error
    exit 1
fi

if ! [ -d $BASEDIR ]
then
    echo "${0##*/}: missing project base directory" >&2 ; exit 1
elif [[ $BASEDIR != /* ]]
then
    BASEDIR=$(cd "$BASEDIR" && pwd)
fi

PACKAGENAME=${PACKAGENAME:-$(python setup.py --name)}
TARGETDIR=$BASEDIR/$PACKAGENAME
if ! [ -d $TARGETDIR ] ; then
    echo "${0##*/}: invalid project package name" >&2 ; exit 1
fi

BASEDIRESC=`echo $BASEDIR | sed -e 's/\//\\\\\//g'`
find $TARGETDIR -type f -name "*.pyc" -delete

export TARGETDIR=$TARGETDIR
export BASEDIRESC=$BASEDIRESC

python cinder/config/generate_cinder_opts.py

if [ $? -ne 0 ]
then
    echo -en "\n\n#################################################"
    echo -en "\nERROR: Non-zero exit from generate_cinder_opts.py."
    echo -en "\n       See output above for details.\n"
    echo -en "#################################################\n"
    exit 1
fi

oslo-config-generator --config-file=cinder/config/cinder-config-generator.conf

if [ $? -ne 0 ]
then
    echo -en "\n\n#################################################"
    echo -en "\nERROR: Non-zero exit from oslo-config-generator."
    echo -en "\n       See output above for details.\n"
    echo -en "#################################################\n"
    exit 1
fi
if [ ! -s ./etc/cinder/cinder.conf.sample ] ; then
    echo -en "\n\n#########################################################"
    echo -en "\nERROR: etc/cinder/cinder.sample.conf not created properly."
    echo -en "\n        See above output for details.\n"
    echo -en "###########################################################\n"
    exit 1
fi

rm -f cinder/opts.py
rm -f cinder/opts.pyc
