.. _cinder:

============================
Cinder Installation Tutorial
============================

The Block Storage service (cinder) provides block storage devices
to guest instances. The method in which the storage is provisioned and
consumed is determined by the Block Storage driver, or drivers
in the case of a multi-backend configuration. There are a variety of
drivers that are available: NAS/SAN, NFS, iSCSI, Ceph, and more.

The Block Storage API and scheduler services typically run on the controller
nodes. Depending upon the drivers used, the volume service can run
on controller nodes, compute nodes, or standalone storage nodes.

For more information, see the
`Configuration Reference <https://docs.openstack.org/ocata/config-reference/block-storage/volume-drivers.html>`_.

.. toctree::

   overview
   get-started-block-storage
   index-obs
   index-rdo
   index-ubuntu

