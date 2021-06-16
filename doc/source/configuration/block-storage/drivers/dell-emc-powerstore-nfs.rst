==========================
Dell PowerStore NFS Driver
==========================

PowerStore NFS driver enables storing Block Storage service volumes on a
PowerStore storage back end.

Supported operations
~~~~~~~~~~~~~~~~~~~~

- Create, delete, attach and detach volumes.
- Create, delete volume snapshots.
- Create a volume from a snapshot.
- Copy an image to a volume.
- Copy a volume to an image.
- Clone a volume.
- Extend a volume.
- Get volume statistics.
- Attach a volume to multiple servers simultaneously (multiattach).
- Revert a volume to a snapshot.

Driver configuration
~~~~~~~~~~~~~~~~~~~~

Add the following content into ``/etc/cinder/cinder.conf``:

.. code-block:: ini

  [DEFAULT]
  enabled_backends = powerstore-nfs

  [powerstore-nfs]
  volume_driver = cinder.volume.drivers.dell_emc.powerstore.nfs.PowerStoreNFSDriver
  nfs_qcow2_volumes = True
  nfs_snapshot_support = True
  nfs_sparsed_volumes = False
  nas_host = <Ip>
  nas_share_path = /nfs-export
  nas_secure_file_operations = False
  nas_secure_file_permissions = False
  volume_backend_name = powerstore-nfs

Dell PowerStore NFS Copy Offload API
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A feature for effective creation of a volume from snapshot/volume was added
in PowerStore NFS Driver. The dellfcopy utility provides the ability to copy
a file very quickly on a Dell SDNAS filesystem mounted by a client.
To download it, contact your local Dell representative.

The dellfcopy tool is used in the following operations:

- Create a volume from a snapshot.
- Clone a volume.

To use PowerStore NFS driver with this feature, you must install the tool with
the following command:

.. code-block:: console

   # sudo dpkg -i ./dellfcopy_1.3-1_amd64.deb
