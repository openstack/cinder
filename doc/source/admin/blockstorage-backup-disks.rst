===================================
Back up Block Storage service disks
===================================

While you can use the LVM snapshot to create snapshots, you can also use
it to back up your volumes. By using LVM snapshot, you reduce the size
of the backup; only existing data is backed up instead of the entire
volume.

To back up a volume, you must create a snapshot of it. An LVM snapshot
is the exact copy of a logical volume, which contains data in a frozen
state. This prevents data corruption because data cannot be manipulated
during the volume creation process. Remember that the volumes created
through an :command:`openstack volume create` command exist in an LVM
logical volume.

You must also make sure that the operating system is not using the
volume and that all data has been flushed on the guest file systems.
This usually means that those file systems have to be unmounted during
the snapshot creation. They can be mounted again as soon as the logical
volume snapshot has been created.

Before you create the snapshot you must have enough space to save it.
As a precaution, you should have at least twice as much space as the
potential snapshot size. If insufficient space is available, the snapshot
might become corrupted.

For this example assume that a 100 GB volume named ``volume-00000001``
was created for an instance while only 4 GB are used. This example uses
these commands to back up only those 4 GB:

* :command:`lvm2` command. Directly manipulates the volumes.

* :command:`kpartx` command. Discovers the partition table created inside the
  instance.

* :command:`tar` command. Creates a minimum-sized backup.

* :command:`sha1sum` command. Calculates the backup checksum to check its
  consistency.

You can apply this process to volumes of any size.

**To back up Block Storage service disks**

#. Create a snapshot of a used volume

   * Use this command to list all volumes

     .. code-block:: console

        # lvdisplay

   * Create the snapshot; you can do this while the volume is attached
     to an instance:

     .. code-block:: console

        # lvcreate --size 10G --snapshot --name volume-00000001-snapshot \
          /dev/cinder-volumes/volume-00000001

     Use the ``--snapshot`` configuration option to tell LVM that you want a
     snapshot of an already existing volume. The command includes the size
     of the space reserved for the snapshot volume, the name of the snapshot,
     and the path of an already existing volume. Generally, this path
     is ``/dev/cinder-volumes/VOLUME_NAME``.

     The size does not have to be the same as the volume of the snapshot.
     The ``--size`` parameter defines the space that LVM reserves
     for the snapshot volume. As a precaution, the size should be the same
     as that of the original volume, even if the whole space is not
     currently used by the snapshot.

   * Run the :command:`lvdisplay` command again to verify the snapshot:

     .. code-block:: console

        --- Logical volume ---
        LV Name                /dev/cinder-volumes/volume-00000001
        VG Name                cinder-volumes
        LV UUID                gI8hta-p21U-IW2q-hRN1-nTzN-UC2G-dKbdKr
        LV Write Access        read/write
        LV snapshot status     source of
                               /dev/cinder-volumes/volume-00000026-snap [active]
        LV Status              available
        # open                 1
        LV Size                15,00 GiB
        Current LE             3840
        Segments               1
        Allocation             inherit
        Read ahead sectors     auto
        - currently set to     256
        Block device           251:13

        --- Logical volume ---
        LV Name                /dev/cinder-volumes/volume-00000001-snap
        VG Name                cinder-volumes
        LV UUID                HlW3Ep-g5I8-KGQb-IRvi-IRYU-lIKe-wE9zYr
        LV Write Access        read/write
        LV snapshot status     active destination for /dev/cinder-volumes/volume-00000026
        LV Status              available
        # open                 0
        LV Size                15,00 GiB
        Current LE             3840
        COW-table size         10,00 GiB
        COW-table LE           2560
        Allocated to snapshot  0,00%
        Snapshot chunk size    4,00 KiB
        Segments               1
        Allocation             inherit
        Read ahead sectors     auto
        - currently set to     256
        Block device           251:14

#. Partition table discovery

   * To exploit the snapshot with the :command:`tar` command, mount
     your partition on the Block Storage service server.

     The :command:`kpartx` utility discovers and maps table partitions.
     You can use it to view partitions that are created inside the
     instance. Without using the partitions created inside instances,
     you cannot see its content and create efficient backups.

     .. code-block:: console

        # kpartx -av /dev/cinder-volumes/volume-00000001-snapshot

     .. note::

        On a Debian-based distribution, you can use the
        :command:`apt-get install kpartx` command to install
        :command:`kpartx`.

     If the tools successfully find and map the partition table,
     no errors are returned.

   * To check the partition table map, run this command:

     .. code-block:: console

        $ ls /dev/mapper/nova*

     You can see the ``cinder--volumes-volume--00000001--snapshot1``
     partition.

     If you created more than one partition on that volume, you see
     several partitions; for example:
     ``cinder--volumes-volume--00000001--snapshot2``,
     ``cinder--volumes-volume--00000001--snapshot3``, and so on.

   * Mount your partition

     .. code-block:: console

        # mount /dev/mapper/cinder--volumes-volume--volume--00000001--snapshot1 /mnt

     If the partition mounts successfully, no errors are returned.

     You can directly access the data inside the instance. If a message
     prompts you for a partition or you cannot mount it, determine whether
     enough space was allocated for the snapshot or the :command:`kpartx`
     command failed to discover the partition table.

     Allocate more space to the snapshot and try the process again.

#. Use the :command:`tar` command to create archives

   Create a backup of the volume:

   .. code-block:: console

      $ tar --exclude="lost+found" --exclude="some/data/to/exclude" -czf \
        volume-00000001.tar.gz -C /mnt/ /backup/destination

   This command creates a ``tar.gz`` file that contains the data,
   *and data only*. This ensures that you do not waste space by backing
   up empty sectors.

#. Checksum calculation I

   You should always have the checksum for your backup files. When you
   transfer the same file over the network, you can run a checksum
   calculation to ensure that your file was not corrupted during its
   transfer. The checksum is a unique ID for a file. If the checksums are
   different, the file is corrupted.

   Run this command to run a checksum for your file and save the result
   to a file:

   .. code-block:: console

      $ sha1sum volume-00000001.tar.gz > volume-00000001.checksum

   .. note::

      Use the :command:`sha1sum` command carefully because the time it
      takes to complete the calculation is directly proportional to the
      size of the file.

      Depending on your CPU, the process might take a long time for
      files larger than around 4 to 6 GB.

#. After work cleaning

   Now that you have an efficient and consistent backup, use this command
   to clean up the file system:

   * Unmount the volume.

     .. code-block:: console

        $ umount /mnt

   * Delete the partition table.

     .. code-block:: console

        $ kpartx -dv /dev/cinder-volumes/volume-00000001-snapshot

   * Remove the snapshot.

     .. code-block:: console

        $ lvremove -f /dev/cinder-volumes/volume-00000001-snapshot

   Repeat these steps for all your volumes.

#. Automate your backups

   Because more and more volumes might be allocated to your Block Storage
   service, you might want to automate your backups.
   The `SCR_5005_V01_NUAC-OPENSTACK-EBS-volumes-backup.sh`_ script assists
   you with this task. The script performs the operations from the previous
   example, but also provides a mail report and runs the backup based on
   the ``backups_retention_days`` setting.

   Launch this script from the server that runs the Block Storage service.

   This example shows a mail report:

   .. code-block:: console

      Backup Start Time - 07/10 at 01:00:01
      Current retention - 7 days

      The backup volume is mounted. Proceed...
      Removing old backups...  : /BACKUPS/EBS-VOL/volume-00000019/volume-00000019_28_09_2011.tar.gz
           /BACKUPS/EBS-VOL/volume-00000019 - 0 h 1 m and 21 seconds. Size - 3,5G

      The backup volume is mounted. Proceed...
      Removing old backups...  : /BACKUPS/EBS-VOL/volume-0000001a/volume-0000001a_28_09_2011.tar.gz
           /BACKUPS/EBS-VOL/volume-0000001a - 0 h 4 m and 15 seconds. Size - 6,9G
      ---------------------------------------
      Total backups size - 267G - Used space : 35%
      Total execution time - 1 h 75 m and 35 seconds

   The script also enables you to SSH to your instances and run a
   :command:`mysqldump` command into them. To make this work, enable
   the connection to the Compute project keys. If you do not want to
   run the :command:`mysqldump` command, you can add
   ``enable_mysql_dump=0`` to the script to turn off this functionality.


.. Links
.. _`SCR_5005_V01_NUAC-OPENSTACK-EBS-volumes-backup.sh`: https://github.com/Razique/BashStuff/blob/master/SYSTEMS/OpenStack/SCR_5005_V01_NUAC-OPENSTACK-EBS-volumes-backup.sh
