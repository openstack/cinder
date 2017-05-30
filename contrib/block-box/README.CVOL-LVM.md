You'll need to modify how you're doing things to get to the iscsi Target.
Specifically, using a Docker network hoses everything because the IP of the
target is the internal containers IP NOT the IP of the host.

Setting `network_mode: host` solves this, but that creates a new problem.
Can't use `link` when using network_mode: host.

Sigh... so; docker run has "add-host=host:IP" that we should be able to find
equivalent in compose.  We just need to define a network and assign IP's to the
other containers, then this should work.

Compose looks like this:
    extra_hosts:
      - "hostname:1.1.1.1"
      - "anotherhost:2.2.2.2"

This just adds entries to /etc/hosts for you.  Kinda handy

So, if we create a network and assign IP's to the supporting cast (rabbit,
mariadb api etc etc) we can then just use this to make them accessible instead
of using `link`

OHHHH!  Add `ipc_mode: host`, shared memory; may speed things up a bit?

Finally... for reference;  The docker run command for this looks something
like:
    `docker run -it \
    -v /dev/:/dev/ \
    -v /run/:/run/:shared -v
    /etc/localtime:/etc/localtime:ro \
    --net host \
    --privileged cinder_debian \
    bash`

### https://wiki.debian.org/LVM
vim /etc/lvm/lvm.conf
    # disable udev_ stuff
/usr/sbin/tgtd
tgtadm --lld iscsi --op show --mode target
tgtadm --lld iscsi --op new --mode target --tid 1 -T iqn.2001-04.com.example:storage.disk2.amiens.sys1.xyz
tgtadm --lld iscsi --mode logicalunit --op new --tid 1 --lun 1 -b /dev/vg-group/lv
tgtadm --lld iscsi --op bind --mode target --tid 1 -I ALL

##  Notes here:  https://wiki.debian.org/SAN/iSCSI/open-iscsi

### Initiator side
iscsiadm -m discovery -t sendtargets -p <portalip>
iscsiadm -m node --targetname=<targetname> --login

