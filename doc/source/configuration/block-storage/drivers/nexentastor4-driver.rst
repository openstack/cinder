=====================================
NexentaStor 4.x NFS and iSCSI drivers
=====================================

NexentaStor is an Open Source-driven Software-Defined Storage (OpenSDS)
platform delivering unified file (NFS and SMB) and block (FC and iSCSI)
storage services, runs on industry standard hardware, scales from tens of
terabytes to petabyte configurations, and includes all data management
functionality by default.

For NexentaStor 4.x user documentation, visit
https://nexenta.com/products/downloads/nexentastor.

Supported operations
~~~~~~~~~~~~~~~~~~~~

* Create, delete, attach, and detach volumes.

* Create, list, and delete volume snapshots.

* Create a volume from a snapshot.

* Copy an image to a volume.

* Copy a volume to an image.

* Clone a volume.

* Extend a volume.

* Migrate a volume.

* Change volume type.

Nexenta iSCSI driver
~~~~~~~~~~~~~~~~~~~~

The Nexenta iSCSI driver allows you to use a NexentaStor appliance to store
Compute volumes. Every Compute volume is represented by a single zvol in a
predefined Nexenta namespace. The Nexenta iSCSI volume driver should work with
all versions of NexentaStor.

The NexentaStor appliance must be installed and configured according to the
relevant Nexenta documentation. A volume and an enclosing namespace must be
created for all iSCSI volumes to be accessed through the volume driver. This
should be done as specified in the release-specific NexentaStor documentation.

The NexentaStor Appliance iSCSI driver is selected using the normal procedures
for one or multiple backend volume drivers.

You must configure these items for each NexentaStor appliance that the iSCSI
volume driver controls:

#. Make the following changes on the volume node ``/etc/cinder/cinder.conf``
   file.

   .. code-block:: ini

      # Enable Nexenta iSCSI driver
      volume_driver=cinder.volume.drivers.nexenta.iscsi.NexentaISCSIDriver

      # IP address of NexentaStor host (string value)
      nexenta_host=HOST-IP

      # Username for NexentaStor REST (string value)
      nexenta_user=USERNAME

      # Port for Rest API (integer value)
      nexenta_rest_port=8457

      # Password for NexentaStor REST (string value)
      nexenta_password=PASSWORD

      # Volume on NexentaStor appliance (string value)
      nexenta_volume=volume_name


.. note::

      nexenta_volume represents a zpool which is called volume on NS appliance. It must be pre-created before enabling the driver.


#. Save the changes to the ``/etc/cinder/cinder.conf`` file and
   restart the ``cinder-volume`` service.



Nexenta NFS driver
~~~~~~~~~~~~~~~~~~
The Nexenta NFS driver allows you to use NexentaStor appliance to store
Compute volumes via NFS. Every Compute volume is represented by a single
NFS file within a shared directory.

While the NFS protocols standardize file access for users, they do not
standardize administrative actions such as taking snapshots or replicating
file systems. The OpenStack Volume Drivers bring a common interface to these
operations. The Nexenta NFS driver implements these standard actions using
the ZFS management plane that is already deployed on NexentaStor appliances.

The Nexenta NFS volume driver should work with all versions of NexentaStor.
The NexentaStor appliance must be installed and configured according to the
relevant Nexenta documentation. A single-parent file system must be created
for all virtual disk directories supported for OpenStack. This directory must
be created and exported on each NexentaStor appliance. This should be done as
specified in the release- specific NexentaStor documentation.

You must configure these items for each NexentaStor appliance that the NFS
volume driver controls:

#. Make the following changes on the volume node ``/etc/cinder/cinder.conf``
   file.

   .. code-block:: ini

      # Enable Nexenta NFS driver
      volume_driver=cinder.volume.drivers.nexenta.nfs.NexentaNfsDriver

      # Path to shares config file
      nexenta_shares_config=/home/ubuntu/shares.cfg

   .. note::

      Add your list of Nexenta NFS servers to the file you specified with the
      ``nexenta_shares_config`` option. For example, this is how this file should look:

   .. code-block:: bash

      192.168.1.200:/volumes/VOLUME_NAME/NFS_SHARE http://USER:PASSWORD@192.168.1.200:8457
      192.168.1.201:/volumes/VOLUME_NAME/NFS_SHARE http://USER:PASSWORD@192.168.1.201:8457
      192.168.1.202:/volumes/VOLUME_NAME/NFS_SHARE http://USER:PASSWORD@192.168.1.202:8457

Each line in this file represents an NFS share. The first part of the line is
the NFS share URL, the second line is the connection URL to the NexentaStor
Appliance.

Driver options
~~~~~~~~~~~~~~

Nexenta Driver supports these options:

.. include:: ../../tables/cinder-nexenta.inc
