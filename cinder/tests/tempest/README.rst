===============================================
Tempest Integration for Cinder
===============================================

This directory contains additional Cinder tempest tests.

See the tempest plugin docs for information on using it:
http://docs.openstack.org/developer/tempest/plugin.html#using-plugins

To run all tests from this plugin, install cinder into your environment. Then
from the tempest directory run::

    $ tox -e all-plugin -- volume


It is expected that Cinder third party CI's use the all-plugin tox environment
above for all test runs. Developers can also use this locally to perform more
extensive testing.

Any typical devstack instance should be able to run all Cinder plugin tests.
For completeness, here is an example of a devstack local.conf that should
work. Update backend information to fit your environment.

::

    [[local|localrc]]
    VIRT_DRIVER=libvirt
    ADMIN_PASSWORD=secret
    SERVICE_TOKEN=$ADMIN_PASSWORD
    MYSQL_PASSWORD=$ADMIN_PASSWORD
    RABBIT_PASSWORD=$ADMIN_PASSWORD
    SERVICE_PASSWORD=$ADMIN_PASSWORD
    SCREEN_LOGDIR=/opt/stack/screen-logs
    LOGFILE=$DEST/logs/stack.sh.log
    LOGDAYS=2
    SYSLOG=False
    LOG_COLOR=False
    RECLONE=yes
    ENABLED_SERVICES=c-api,c-sch,c-vol,cinder,dstat,g-api,g-reg,key,mysql,
                     n-api,n-cond,n-cpu,n-crt,n-net,n-sch,rabbit,tempest
    CINDER_ENABLED_BACKENDS=lvmdriver-1
    CINDER_DEFAULT_VOLUME_TYPE=lvmdriver-1
    CINDER_VOLUME_CLEAR=none
    TEMPEST_ENABLED_BACKENDS=lvmdriver-1
    TEMPEST_VOLUME_DRIVER=lvmdriver-1
    TEMPEST_VOLUME_VENDOR="Open Source"
    TEMPEST_STORAGE_PROTOCOL=iSCSI
    LIBVIRT_FIREWALL_DRIVER=nova.virt.firewall.NoopFirewallDriver
    VIRT_DRIVER=libvirt
    ACTIVE_TIMEOUT=120
    BOOT_TIMEOUT=120
    ASSOCIATE_TIMEOUT=120
    TERMINATE_TIMEOUT=120


    [[post-config|$CINDER_CONF]]
    [DEFAULT]
    [lvmdriver-1]
    volume_driver=cinder.volume.drivers.lvm.LVMISCSIDriver
    volume_group=stack-volumes-1
    volume_backend_name=lvmdriver-1``

