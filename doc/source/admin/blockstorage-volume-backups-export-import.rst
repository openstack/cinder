.. _volume_backups_export_import:

=================================
Export and import backup metadata
=================================


A volume backup can only be restored on the same Block Storage service. This
is because restoring a volume from a backup requires metadata available on
the database used by the Block Storage service.

.. note::

   For information about how to back up and restore a volume, see
   the section called :ref:`volume_backups`.

You can, however, export the metadata of a volume backup. To do so, run
this command as an OpenStack ``admin`` user (presumably, after creating
a volume backup):

.. code-block:: console

   $ cinder backup-export BACKUP_ID

Where ``BACKUP_ID`` is the volume backup's ID. This command should return the
backup's corresponding database information as encoded string metadata.

Exporting and storing this encoded string metadata allows you to completely
restore the backup, even in the event of a catastrophic database failure.
This will preclude the need to back up the entire Block Storage database,
particularly if you only need to keep complete backups of a small subset
of volumes.

If you have placed encryption on your volumes, the encryption will still be
in place when you restore the volume if a UUID encryption key is specified
when creating volumes. Using backup metadata support, UUID keys set up for
a volume (or volumes) will remain valid when you restore a backed-up volume.
The restored volume will remain encrypted, and will be accessible with your
credentials.

In addition, having a volume backup and its backup metadata also provides
volume portability. Specifically, backing up a volume and exporting its
metadata will allow you to restore the volume on a completely different Block
Storage database, or even on a different cloud service. To do so, first
import the backup metadata to the Block Storage database and then restore
the backup.

To import backup metadata, run the following command as an OpenStack
``admin``:

.. code-block:: console

   $ cinder backup-import METADATA

Where ``METADATA`` is the backup metadata exported earlier.

Once you have imported the backup metadata into a Block Storage database,
restore the volume (see the section called :ref:`volume_backups`).
