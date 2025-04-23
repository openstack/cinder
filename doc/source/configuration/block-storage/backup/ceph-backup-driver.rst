==================
Ceph backup driver
==================

The Ceph backup driver backs up volumes of any type to a Ceph back-end
store. The driver can also detect whether the volume to be backed up is
a Ceph RBD volume, and if so, it tries to perform incremental and
differential backups.

For source Ceph RBD volumes, you can perform backups within the same
Ceph pool (not recommended). You can also perform backups between
different Ceph pools and between different Ceph clusters.

At the time of writing, differential backup support in Ceph/librbd was
quite new. This driver attempts a differential backup in the first
instance. If the differential backup fails, the driver falls back to
full backup/copy.

If incremental backups are used, multiple backups of the same volume are
stored as snapshots so that minimal space is consumed in the backup
store. It takes far less time to restore a volume than to take a full
copy.

By default, all incremental backups are held on the source volume storage,
which can take up much disk space on the usually more expensive
primary storage compared to backup storage. Enabling the option
``backup_ceph_max_snapshots`` can save disk space on the source
volume storage by only keeping a limited number of snapshots per backup volume.
After every successful creation of a new incremental backup, the Ceph backup
driver will then ensure that excess snapshots of the corresponding backup
volume are deleted so that only the ``backup_ceph_max_snapshots``
most recent snapshots are kept on the primary storage.
However, this can cause incremental backups to automatically become full
backups instead if a user manually deleted at least
``backup_ceph_max_snapshots`` incremental backups. In that case
the next snapshot, being a full backup, will require more disk space on
the backup storage and will take longer to complete than an incremental
backup would have.

Thus, the option allows to configure a tradeoff between required space on the
source volume storage and required space on the backup storage as well as a
longer backup process under the above conditions.

.. note::

    Block Storage enables you to:

    -  Restore to a new volume, which is the default and recommended
       action.

    -  Restore to the original volume from which the backup was taken.
       The restore action takes a full copy because this is the safest
       action.

To enable the Ceph backup driver, include the following option in the
``cinder.conf`` file:

.. code-block:: ini

    backup_driver = cinder.backup.drivers.ceph.CephBackupDriver

The following configuration options are available for the Ceph backup
driver.

.. config-table::
   :config-target: Ceph backup driver

   cinder.backup.drivers.ceph

This example shows the default options for the Ceph backup driver.

.. code-block:: ini

    backup_ceph_conf=/etc/ceph/ceph.conf
    backup_ceph_user = cinder-backup
    backup_ceph_chunk_size = 134217728
    backup_ceph_pool = backups
    backup_ceph_stripe_unit = 0
    backup_ceph_stripe_count = 0
    backup_ceph_max_snapshots = 0
