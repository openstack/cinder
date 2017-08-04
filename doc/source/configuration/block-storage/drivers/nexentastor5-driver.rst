=====================================
NexentaStor 5.x NFS and iSCSI drivers
=====================================

NexentaStor is an Open Source-driven Software-Defined Storage (OpenSDS)
platform delivering unified file (NFS and SMB) and block (FC and iSCSI)
storage services. NexentaStor runs on industry standard hardware, scales from
tens of terabytes to petabyte configurations, and includes all data management
functionality by default.

For user documentation, see the
`Nexenta Documentation Center <https://nexenta.com/products/documentation>`__.

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

iSCSI driver
~~~~~~~~~~~~

The NexentaStor appliance must be installed and configured according to the
relevant Nexenta documentation. A pool and an enclosing namespace must be
created for all iSCSI volumes to be accessed through the volume driver. This
should be done as specified in the release-specific NexentaStor documentation.

The NexentaStor Appliance iSCSI driver is selected using the normal procedures
for one or multiple back-end volume drivers.


You must configure these items for each NexentaStor appliance that the iSCSI
volume driver controls:

#. Make the following changes on the volume node ``/etc/cinder/cinder.conf``
   file.

   .. code-block:: ini

      # Enable Nexenta iSCSI driver
      volume_driver=cinder.volume.drivers.nexenta.ns5.iscsi.NexentaISCSIDriver

      # IP address of NexentaStor host (string value)
      nexenta_host=HOST-IP

      # Port for Rest API (integer value)
      nexenta_rest_port=8080

      # Username for NexentaStor Rest (string value)
      nexenta_user=USERNAME

      # Password for NexentaStor Rest (string value)
      nexenta_password=PASSWORD

      # Pool on NexentaStor appliance (string value)
      nexenta_volume=volume_name

      # Name of a parent Volume group where cinder created zvols will reside (string value)
      nexenta_volume_group = iscsi

   .. note::

      nexenta_volume represents a zpool, which is called pool on NS 5.x appliance.
      It must be pre-created before enabling the driver.

      Volume group does not need to be pre-created, the driver will create it if does not exist.

#. Save the changes to the ``/etc/cinder/cinder.conf`` file and
   restart the ``cinder-volume`` service.

NFS driver
~~~~~~~~~~
The Nexenta NFS driver allows you to use NexentaStor appliance to store
Compute volumes via NFS. Every Compute volume is represented by a single
NFS file within a shared directory.

While the NFS protocols standardize file access for users, they do not
standardize administrative actions such as taking snapshots or replicating
file systems. The OpenStack Volume Drivers bring a common interface to these
operations. The Nexenta NFS driver implements these standard actions using the
ZFS management plane that already is deployed on NexentaStor appliances.

The NexentaStor appliance must be installed and configured according to the
relevant Nexenta documentation. A single-parent file system must be created
for all virtual disk directories supported for OpenStack.
Create and export the directory on each NexentaStor appliance.

You must configure these items for each NexentaStor appliance that the NFS
volume driver controls:

#. Make the following changes on the volume node ``/etc/cinder/cinder.conf``
   file.

   .. code-block:: ini

      # Enable Nexenta NFS driver
      volume_driver=cinder.volume.drivers.nexenta.ns5.nfs.NexentaNfsDriver

      # IP address or Hostname of NexentaStor host (string value)
      nas_host=HOST-IP

      # Port for Rest API (integer value)
      nexenta_rest_port=8080

      # Path to parent filesystem (string value)
      nas_share_path=POOL/FILESYSTEM

      # Specify NFS version
      nas_mount_options=vers=4

#. Create filesystem on appliance and share via NFS. For example:

   .. code-block:: vim

      "securityContexts": [
         {"readWriteList": [{"allow": true, "etype": "fqnip", "entity": "1.1.1.1"}],
          "root": [{"allow": true, "etype": "fqnip", "entity": "1.1.1.1"}],
          "securityModes": ["sys"]}]

#. Create ACL for the filesystem. For example:

   .. code-block:: json

      {"type": "allow",
      "principal": "everyone@",
      "permissions": ["list_directory","read_data","add_file","write_data",
      "add_subdirectory","append_data","read_xattr","write_xattr","execute",
      "delete_child","read_attributes","write_attributes","delete","read_acl",
      "write_acl","write_owner","synchronize"],
      "flags": ["file_inherit","dir_inherit"]}


Driver options
~~~~~~~~~~~~~~

Nexenta Driver supports these options:

.. include:: ../../tables/cinder-nexenta5.inc
