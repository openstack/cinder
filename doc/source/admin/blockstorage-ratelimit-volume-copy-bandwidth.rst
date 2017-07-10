.. _ratelimit_volume_copy_bandwidth:

================================
Rate-limit volume copy bandwidth
================================

When you create a new volume from an image or an existing volume, or
when you upload a volume image to the Image service, large data copy
may stress disk and network bandwidth. To mitigate slow down of data
access from the instances, OpenStack Block Storage supports rate-limiting
of volume data copy bandwidth.

Configure volume copy bandwidth limit
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To configure the volume copy bandwidth limit, set the
``volume_copy_bps_limit`` option in the configuration groups for each
back end in the ``cinder.conf`` file. This option takes the integer of
maximum bandwidth allowed for volume data copy in byte per second. If
this option is set to ``0``, the rate-limit is disabled.

While multiple volume data copy operations are running in the same back
end, the specified bandwidth is divided to each copy.

Example ``cinder.conf`` configuration file to limit volume copy bandwidth
of ``lvmdriver-1`` up to 100 MiB/s:

.. code-block:: ini

   [lvmdriver-1]
   volume_group=cinder-volumes-1
   volume_driver=cinder.volume.drivers.lvm.LVMVolumeDriver
   volume_backend_name=LVM
   volume_copy_bps_limit=104857600

.. note::

    This feature requires libcgroup to set up blkio cgroup for disk I/O
    bandwidth limit. The libcgroup is provided by the cgroup-bin package
    in Debian and Ubuntu, or by the libcgroup-tools package in Fedora,
    Red Hat Enterprise Linux, CentOS, openSUSE, and SUSE Linux Enterprise.

.. note::

    Some back ends which use remote file systems such as NFS are not
    supported by this feature.
