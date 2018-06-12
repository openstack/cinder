==============
Volume drivers
==============

To use different volume drivers for the cinder-volume service, use the
parameters described in these sections.

These volume drivers are included in the `Block Storage repository
<https://git.openstack.org/cgit/openstack/cinder/>`_. To set a volume
driver, use the ``volume_driver`` flag.

The default is:

.. code-block:: ini

    volume_driver = cinder.volume.drivers.lvm.LVMVolumeDriver

Note that some third party storage systems may maintain more detailed
configuration documentation elsewhere. Contact your vendor for more information
if needed.

Driver Configuration Reference
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
.. sort by the drivers by open source software
.. and the drivers for proprietary components

.. toctree::
   :maxdepth: 1

   drivers/ceph-rbd-volume-driver
   drivers/lvm-volume-driver
   drivers/nfs-volume-driver
   drivers/sheepdog-driver
   drivers/coprhd-driver
   drivers/datacore-volume-driver
   drivers/datera-volume-driver
   drivers/dell-equallogic-driver
   drivers/dell-storagecenter-driver
   drivers/dell-emc-unity-driver
   drivers/dell-emc-vnx-driver
   drivers/dell-emc-vmax-driver
   drivers/dell-emc-vxflex-driver
   drivers/emc-xtremio-driver
   drivers/drbd-driver
   drivers/fujitsu-eternus-dx-driver
   drivers/hgst-driver
   drivers/hpe-3par-driver
   drivers/hpe-lefthand-driver
   drivers/hp-msa-driver
   drivers/huawei-storage-driver
   drivers/ibm-flashsystem-volume-driver
   drivers/ibm-gpfs-volume-driver
   drivers/ibm-storage-volume-driver
   drivers/ibm-storwize-svc-driver
   drivers/infinidat-volume-driver
   drivers/inspur-instorage-driver
   drivers/itri-disco-driver
   drivers/kaminario-driver
   drivers/lenovo-driver
   drivers/nec-storage-m-series-driver
   drivers/netapp-volume-driver
   drivers/nimble-volume-driver
   drivers/nexentaedge-driver
   drivers/nexentastor4-driver
   drivers/nexentastor5-driver
   drivers/prophetstor-dpl-driver
   drivers/pure-storage-driver
   drivers/quobyte-driver
   drivers/solidfire-volume-driver
   drivers/storpool-volume-driver
   drivers/synology-dsm-driver
   drivers/tintri-volume-driver
   drivers/veritas-access-iscsi-driver
   drivers/vzstorage-driver
   drivers/vmware-vmdk-driver
   drivers/windows-iscsi-volume-driver
   drivers/windows-smb-volume-driver
   drivers/zadara-volume-driver
   drivers/zfssa-iscsi-driver
   drivers/zfssa-nfs-driver
