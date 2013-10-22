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

cat >> $OUTPUTFILE <<-EOF_CAT
[keystone_authtoken]

#
# Options defined in keystoneclient's authtoken middleware
#

# Host providing the admin Identity API endpoint
auth_host = 127.0.0.1

# Port of the admin Identity API endpoint
auth_port = 35357

# Protocol of the admin Identity API endpoint
auth_protocol = http

# Keystone service account tenant name to validate user tokens
admin_tenant_name = %SERVICE_TENANT_NAME%

# Keystone account username
admin_user = %SERVICE_USER%

# Keystone account password
admin_password = %SERVICE_PASSWORD%

# Directory used to cache files related to PKI tokens
# signing_dir is configurable, but the default behavior of the authtoken
# middleware should be sufficient.  It will create a temporary directory
# in the home directory for the user the cinder process is running as.
#signing_dir = /var/lib/cinder/keystone-signing
EOF_CAT
