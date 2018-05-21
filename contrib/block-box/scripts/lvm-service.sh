#!/bin/bash

YUM = $(which yum)
APT = $(which apt-get)

# There's a few things that aren't in the older LOCI images,
# we'll add them here just to be safe
if [[ ! -z $YUM ]]; then
	yum install -y epel-release
	yum update -y
	yum install -y scsi-target-utils
elif [[ ! -z $APT ]]; then
	apt-get update -y
	apt-get install -y thin-provisioning-tools

else:
	echo "I don't know how to install with this package manager"
	exit 1;
fi

sed -i -e 's/udev_sync = 1/udev_sync = 0/g' /etc/lvm/lvm.conf
sed -i -e 's/udev_rules = 1/udev_rules = 0/g' /etc/lvm/lvm.conf
sed -i -e 's/use_lvmetad = 0/use_lvmetad =1/g' /etc/lvm/lvm.conf
echo "include /var/lib/cinder/volumes/*" >> /etc/tgt/targets.conf
/usr/sbin/tgtd
cinder-volume -d
