#!/usr/bin/env bash

print_hint() {
    echo "Try \`${0##*/} --help' for more information." >&2
}

PARSED_OPTIONS=$(getopt -n "${0##*/}" -o ho: \
                 --long help,output-dir: -- "$@")

if [ $? != 0 ] ; then print_hint ; exit 1 ; fi

eval set -- "$PARSED_OPTIONS"

while true; do
    case "$1" in
        -h|--help)
            echo "${0##*/} [options]"
            echo ""
            echo "options:"
            echo "-h, --help                show brief help"
            echo "-o, --output-dir=DIR      File output directory"
            exit 0
            ;;
        -o|--output-dir)
            shift
            OUTPUTDIR=`echo $1 | sed -e 's/\/*$//g'`
            shift
            ;;
        --)
            break
            ;;
    esac
done

OUTPUTDIR=${OUTPUTDIR:-etc/cinder}
if ! [ -d $OUTPUTDIR ]
then
    echo "${0##*/}: cannot access \`$OUTPUTDIR': No such file or directory" >&2
    exit 1
fi

OUTPUTFILE=$OUTPUTDIR/cinder.conf.sample
FILES=$(find cinder -type f -name "*.py" ! -path "cinder/tests/*" -exec \
    grep -l "Opt(" {} \; | sort -u)

PYTHONPATH=./:${PYTHONPATH} \
    python $(dirname "$0")/extract_opts.py ${FILES} > \
    $OUTPUTFILE

# When we use openstack.common.config.generate we won't need this any more
sed -i 's/^#connection=sqlite.*/#connection=sqlite:\/\/\/\/cinder\/openstack\/common\/db\/$sqlite_db/' $OUTPUTFILE
