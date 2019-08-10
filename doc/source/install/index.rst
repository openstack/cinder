.. _cinder:

=========================
Cinder Installation Guide
=========================

The Block Storage service (cinder) provides block storage devices
to guest instances. The method in which the storage is provisioned and
consumed is determined by the Block Storage driver, or drivers
in the case of a multi-backend configuration. There are a variety of
drivers that are available: NAS/SAN, NFS, iSCSI, Ceph, and more.

The Block Storage API and scheduler services typically run on the controller
nodes. Depending upon the drivers used, the volume service can run
on controller nodes, compute nodes, or standalone storage nodes.

For more information, see the :doc:`Configuration
Reference </configuration/block-storage/volume-drivers>`.


Prerequisites
~~~~~~~~~~~~~

This documentation specifically covers the installation of the Cinder Block
Storage service. Before following this guide you will need to prepare your
OpenStack environment using the instructions in the
`OpenStack Installation Guide <https://docs.openstack.org/install-guide/>`_.

Once able to 'Launch an instance' in your OpenStack environment follow the
instructions below to add Cinder to the base environment.


Adding Cinder to your OpenStack Environment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The following links describe how to install the Cinder Block Storage Service:

.. toctree::

   get-started-block-storage
   index-obs
   index-rdo
   index-ubuntu
   index-windows

