.. _volume_backups:

=========================================
Back up and restore volumes and snapshots
=========================================

The ``openstack`` command-line interface provides the tools for creating a
volume backup. You can restore a volume from a backup as long as the
backup's associated database information (or backup metadata) is intact
in the Block Storage database.

Run this command to create a backup of a volume:

.. code-block:: console

   $ openstack volume backup create [--incremental] [--force] VOLUME

Where ``VOLUME`` is the name or ID of the volume, ``incremental`` is
a flag that indicates whether an incremental backup should be performed,
and ``force`` is a flag that allows or disallows backup of a volume
when the volume is attached to an instance.

Without the ``incremental`` flag, a full backup is created by default.
With the ``incremental`` flag, an incremental backup is created.

Without the ``force`` flag, the volume will be backed up only if its
status is ``available``. With the ``force`` flag, the volume will be
backed up whether its status is ``available`` or ``in-use``. A volume
is ``in-use`` when it is attached to an instance. The backup of an
``in-use`` volume means your data is crash consistent. The ``force``
flag is False by default.

.. note::

   The ``incremental`` and ``force`` flags are only available for block
   storage API v2. You have to specify ``[--os-volume-api-version 2]`` in the
   ``cinder`` command-line interface to use this parameter.

.. note::

   The ``force`` flag is new in OpenStack Liberty.

The incremental backup is based on a parent backup which is an existing
backup with the latest timestamp. The parent backup can be a full backup
or an incremental backup depending on the timestamp.


.. note::

   The first backup of a volume has to be a full backup. Attempting to do
   an incremental backup without any existing backups will fail.
   There is an ``is_incremental`` flag that indicates whether a backup is
   incremental when showing details on the backup.
   Another flag, ``has_dependent_backups``, returned when showing backup
   details, will indicate whether the backup has dependent backups.
   If it is ``true``, attempting to delete this backup will fail.

A new configure option ``backup_swift_block_size`` is introduced into
``cinder.conf`` for the default Swift backup driver. This is the size in
bytes that changes are tracked for incremental backups. The existing
``backup_swift_object_size`` option, the size in bytes of Swift backup
objects, has to be a multiple of ``backup_swift_block_size``. The default
is 32768 for ``backup_swift_block_size``, and the default is 52428800 for
``backup_swift_object_size``.

The configuration option ``backup_swift_enable_progress_timer`` in
``cinder.conf`` is used when backing up the volume to Object Storage
back end. This option enables or disables the timer. It is enabled by default
to send the periodic progress notifications to the Telemetry service.

This command also returns a backup ID. Use this backup ID when restoring
the volume:

.. code-block:: console

   $ openstack volume backup restore BACKUP_ID VOLUME_ID

When restoring from a full backup, it is a full restore.

When restoring from an incremental backup, a list of backups is built based
on the IDs of the parent backups. A full restore is performed based on the
full backup first, then restore is done based on the incremental backup,
laying on top of it in order.

You can view a backup list with the :command:`openstack volume backup list`
command. Optional arguments to clarify the status of your backups
include: running ``--name``, ``--status``, and
``--volume`` to filter through backups by the specified name,
status, or volume-id. Search with ``--all-projects`` for details of the
projects associated with the listed backups.

Because volume backups are dependent on the Block Storage database, you must
also back up your Block Storage database regularly to ensure data recovery.

.. note::

   Alternatively, you can export and save the metadata of selected volume
   backups. Doing so precludes the need to back up the entire Block Storage
   database. This is useful if you need only a small subset of volumes to
   survive a catastrophic database failure.

   If you specify a UUID encryption key when setting up the volume
   specifications, the backup metadata ensures that the key will remain valid
   when you back up and restore the volume.

   For more information about how to export and import volume backup metadata,
   see the section called :ref:`volume_backups_export_import`.

By default, the swift object store is used for the backup repository.

If instead you want to use an NFS export as the backup repository, add the
following configuration options to the ``[DEFAULT]`` section of the
``cinder.conf`` file and restart the Block Storage services:

.. code-block:: ini

   backup_driver = cinder.backup.drivers.nfs
   backup_share = HOST:EXPORT_PATH

For the ``backup_share`` option, replace ``HOST`` with the DNS resolvable
host name or the IP address of the storage server for the NFS share, and
``EXPORT_PATH`` with the path to that share. If your environment requires
that non-default mount options be specified for the share, set these as
follows:

.. code-block:: ini

   backup_mount_options = MOUNT_OPTIONS

``MOUNT_OPTIONS`` is a comma-separated string of NFS mount options as detailed
in the NFS man page.

There are several other options whose default values may be overridden as
appropriate for your environment:

.. code-block:: ini

   backup_compression_algorithm = zlib
   backup_sha_block_size_bytes = 32768
   backup_file_size = 1999994880

The option ``backup_compression_algorithm`` can be set to ``bz2`` or ``None``.
The latter can be a useful setting when the server providing the share for the
backup repository itself performs deduplication or compression on the backup
data.

The option ``backup_file_size`` must be a multiple of
``backup_sha_block_size_bytes``. It is effectively the maximum file size to be
used, given your environment, to hold backup data. Volumes larger than this
will be stored in multiple files in the backup repository. The
``backup_sha_block_size_bytes`` option determines the size of blocks from the
cinder volume being backed up on which digital signatures are calculated in
order to enable incremental backup capability.

You also have the option of resetting the state of a backup. When creating or
restoring a backup, sometimes it may get stuck in the creating or restoring
states due to problems like the database or rabbitmq being down. In situations
like these resetting the state of the backup can restore it to a functional
status.

Run this command to restore the state of a backup:

.. code-block:: console

   $ cinder backup-reset-state [--state STATE] BACKUP_ID-1 BACKUP_ID-2 ...

Run this command to create a backup of a snapshot:

.. code-block:: console

   $ openstack volume backup create [--incremental] [--force] \
     [--snapshot SNAPSHOT_ID] VOLUME

Where ``VOLUME`` is the name or ID of the volume, ``SNAPSHOT_ID`` is the ID of
the volume's snapshot.
