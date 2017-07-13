==============
Volume drivers
==============

.. sort by the drivers by open source software
.. and the drivers for proprietary components

.. toctree::
   :maxdepth: 1

   drivers/ceph-rbd-volume-driver.rst
   drivers/lvm-volume-driver.rst
   drivers/nfs-volume-driver.rst
   drivers/sheepdog-driver.rst
   drivers/smbfs-volume-driver.rst
   drivers/blockbridge-eps-driver.rst
   drivers/cloudbyte-driver.rst
   drivers/coho-data-driver.rst
   drivers/coprhd-driver.rst
   drivers/datera-volume-driver.rst
   drivers/dell-emc-scaleio-driver.rst
   drivers/dell-emc-unity-driver.rst
   drivers/dell-equallogic-driver.rst
   drivers/dell-storagecenter-driver.rst
   drivers/dothill-driver.rst
   drivers/emc-vmax-driver.rst
   drivers/emc-vnx-driver.rst
   drivers/emc-xtremio-driver.rst
   drivers/falconstor-fss-driver.rst
   drivers/fujitsu-eternus-dx-driver.rst
   drivers/hds-hnas-driver.rst
   drivers/hitachi-storage-volume-driver.rst
   drivers/hpe-3par-driver.rst
   drivers/hpe-lefthand-driver.rst
   drivers/hp-msa-driver.rst
   drivers/huawei-storage-driver.rst
   drivers/ibm-gpfs-volume-driver.rst
   drivers/ibm-storwize-svc-driver.rst
   drivers/ibm-storage-volume-driver.rst
   drivers/ibm-flashsystem-volume-driver.rst
   drivers/infinidat-volume-driver.rst
   drivers/infortrend-volume-driver.rst
   drivers/itri-disco-driver.rst
   drivers/kaminario-driver.rst
   drivers/lenovo-driver.rst
   drivers/nec-storage-m-series-driver.rst
   drivers/netapp-volume-driver.rst
   drivers/nimble-volume-driver.rst
   drivers/nexentastor4-driver.rst
   drivers/nexentastor5-driver.rst
   drivers/nexentaedge-driver.rst
   drivers/prophetstor-dpl-driver.rst
   drivers/pure-storage-driver.rst
   drivers/quobyte-driver.rst
   drivers/scality-sofs-driver.rst
   drivers/solidfire-volume-driver.rst
   drivers/synology-dsm-driver.rst
   drivers/tintri-volume-driver.rst
   drivers/violin-v7000-driver.rst
   drivers/vzstorage-driver.rst
   drivers/vmware-vmdk-driver.rst
   drivers/windows-iscsi-volume-driver.rst
   drivers/xio-volume-driver.rst
   drivers/zadara-volume-driver.rst
   drivers/zfssa-iscsi-driver.rst
   drivers/zfssa-nfs-driver.rst
   drivers/zte-storage-driver.rst

To use different volume drivers for the cinder-volume service, use the
parameters described in these sections.

The volume drivers are included in the `Block Storage repository
<https://git.openstack.org/cgit/openstack/cinder/>`_. To set a volume
driver, use the ``volume_driver`` flag. The default is:

.. code-block:: ini

    volume_driver = cinder.volume.drivers.lvm.LVMVolumeDriver
