==========
NFS driver
==========

The Network File System (NFS) is a distributed file system protocol
originally developed by Sun Microsystems in 1984. An NFS server
``exports`` one or more of its file systems, known as ``shares``.
An NFS client can mount these exported shares on its own file system.
You can perform file actions on this mounted remote file system as
if the file system were local.

How the NFS driver works
~~~~~~~~~~~~~~~~~~~~~~~~

The NFS driver, and other drivers based on it, work quite differently
than a traditional block storage driver.

The NFS driver does not actually allow an instance to access a storage
device at the block level. Instead, files are created on an NFS share
and mapped to instances, which emulates a block device.
This works in a similar way to QEMU, which stores instances in the
``/var/lib/nova/instances`` directory.

Enable the NFS driver and related options
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To use Cinder with the NFS driver, first set the ``volume_driver``
in the ``cinder.conf`` configuration file:

.. code-block:: ini

   volume_driver=cinder.volume.drivers.nfs.NfsDriver

The following table contains the options supported by the NFS driver.

.. include:: ../../tables/cinder-storage_nfs.inc

.. note::

   As of the Icehouse release, the NFS driver (and other drivers based
   off it) will attempt to mount shares using version 4.1 of the NFS
   protocol (including pNFS). If the mount attempt is unsuccessful due
   to a lack of client or server support, a subsequent mount attempt
   that requests the default behavior of the :command:`mount.nfs` command
   will be performed. On most distributions, the default behavior is to
   attempt mounting first with NFS v4.0, then silently fall back to NFS
   v3.0 if necessary. If the ``nfs_mount_options`` configuration option
   contains a request for a specific version of NFS to be used, or if
   specific options are specified in the shares configuration file
   specified by the ``nfs_shares_config`` configuration option, the
   mount will be attempted as requested with no subsequent attempts.

How to use the NFS driver
~~~~~~~~~~~~~~~~~~~~~~~~~

Creating an NFS server is outside the scope of this document.

Configure with one NFS server
-----------------------------

This example assumes access to the following NFS server and mount point:

* 192.168.1.200:/storage

This example demonstrates the usage of this driver with one NFS server.

Set the ``nas_host`` option to the IP address or host name of your NFS
server, and the ``nas_share_path`` option to the NFS export path:

.. code-block:: ini

   nas_host = 192.168.1.200
   nas_share_path = /storage

Configure with multiple NFS servers
-----------------------------------

.. note::

   You can use the multiple NFS servers with `cinder multi back ends
   <https://wiki.openstack.org/wiki/Cinder-multi-backend>`_ feature.
   Configure the :ref:`enabled_backends <cinder-storage>` option with
   multiple values, and use the ``nas_host`` and ``nas_share`` options
   for each back end as described above.

The below example is another method to use multiple NFS servers,
and demonstrates the usage of this driver with multiple NFS servers.
Multiple servers are not required. One is usually enough.

This example assumes access to the following NFS servers and mount points:

* 192.168.1.200:/storage
* 192.168.1.201:/storage
* 192.168.1.202:/storage

#. Add your list of NFS servers to the file you specified with the
   ``nfs_shares_config`` option. For example, if the value of this option
   was set to ``/etc/cinder/shares.txt`` file, then:

   .. code-block:: console

      # cat /etc/cinder/shares.txt
      192.168.1.200:/storage
      192.168.1.201:/storage
      192.168.1.202:/storage

   Comments are allowed in this file. They begin with a ``#``.

#. Configure the ``nfs_mount_point_base`` option. This is a directory
   where ``cinder-volume`` mounts all NFS shares stored in the ``shares.txt``
   file. For this example, ``/var/lib/cinder/nfs`` is used. You can,
   of course, use the default value of ``$state_path/mnt``.

#. Start the ``cinder-volume`` service. ``/var/lib/cinder/nfs`` should
   now contain a directory for each NFS share specified in the ``shares.txt``
   file. The name of each directory is a hashed name:

   .. code-block:: console

      # ls /var/lib/cinder/nfs/
      ...
      46c5db75dc3a3a50a10bfd1a456a9f3f
      ...

#. You can now create volumes as you normally would:

   .. code-block:: console

      $ openstack volume create --size 5 MYVOLUME
      # ls /var/lib/cinder/nfs/46c5db75dc3a3a50a10bfd1a456a9f3f
      volume-a8862558-e6d6-4648-b5df-bb84f31c8935

This volume can also be attached and deleted just like other volumes.
However, snapshotting is **not** supported.

NFS driver notes
~~~~~~~~~~~~~~~~

* ``cinder-volume`` manages the mounting of the NFS shares as well as
  volume creation on the shares. Keep this in mind when planning your
  OpenStack architecture. If you have one master NFS server, it might
  make sense to only have one ``cinder-volume`` service to handle all
  requests to that NFS server. However, if that single server is unable
  to handle all requests, more than one ``cinder-volume`` service is
  needed as well as potentially more than one NFS server.

* Because data is stored in a file and not actually on a block storage
  device, you might not see the same IO performance as you would with
  a traditional block storage driver. Please test accordingly.

* Despite possible IO performance loss, having volume data stored in
  a file might be beneficial. For example, backing up volumes can be
  as easy as copying the volume files.

.. note::

   Regular IO flushing and syncing still stands.
