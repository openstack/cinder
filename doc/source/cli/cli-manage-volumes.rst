.. _volume:

==============
Manage volumes
==============

A volume is a detachable block storage device, similar to a USB hard
drive. You can attach a volume to only one instance. Use  the ``openstack``
client commands to create and manage volumes.

Migrate a volume
~~~~~~~~~~~~~~~~

As an administrator, you can migrate a volume with its data from one
location to another in a manner that is transparent to users and
workloads. You can migrate only detached volumes with no snapshots.

Possible use cases for data migration include:

*  Bring down a physical storage device for maintenance without
   disrupting workloads.

*  Modify the properties of a volume.

*  Free up space in a thinly-provisioned back end.

Migrate a volume with the :command:`openstack volume migrate` command, as shown
in the following example:

.. code-block:: console

   $ openstack volume migrate [-h] --host <host> [--force-host-copy]
                                     [--lock-volume | --unlock-volume]
                                     <volume>

In this example, ``--force-host-copy`` forces the generic
host-based migration mechanism and bypasses any driver optimizations.
``--lock-volume | --unlock-volume`` applies to the available volume.
To determine whether the termination of volume migration caused by other
commands. ``--lock-volume`` locks the volume state and does not allow the
migration to be aborted.

.. note::

   If the volume has snapshots, the specified host destination cannot accept
   the volume. If the user is not an administrator, the migration fails.

Create a volume
~~~~~~~~~~~~~~~

This example creates a ``my-new-volume`` volume based on an image.

#. List images, and note the ID of the image that you want to use for your
   volume:

   .. code-block:: console

      $ openstack image list
      +--------------------------------------+---------------------------------+
      | ID                                   | Name                            |
      +--------------------------------------+---------------------------------+
      | 8bf4dc2a-bf78-4dd1-aefa-f3347cf638c8 | cirros-0.3.5-x86_64-uec         |
      | 9ff9bb2e-3a1d-4d98-acb5-b1d3225aca6c | cirros-0.3.5-x86_64-uec-kernel  |
      | 4b227119-68a1-4b28-8505-f94c6ea4c6dc | cirros-0.3.5-x86_64-uec-ramdisk |
      +--------------------------------------+---------------------------------+


#. List the availability zones, and note the ID of the availability zone in
   which you want to create your volume:

   .. code-block:: console

      $ openstack availability zone list
      +------+-----------+
      | Name |   Status  |
      +------+-----------+
      | nova | available |
      +------+-----------+

#. Create a volume with 8 gibibytes (GiB) of space, and specify the
   availability zone and image:

   .. code-block:: console

      $ openstack volume create --image 8bf4dc2a-bf78-4dd1-aefa-f3347cf638c8 \
        --size 8 --availability-zone nova my-new-volume

      +------------------------------+--------------------------------------+
      | Property                     | Value                                |
      +------------------------------+--------------------------------------+
      | attachments                  | []                                   |
      | availability_zone            | nova                                 |
      | bootable                     | false                                |
      | consistencygroup_id          | None                                 |
      | created_at                   | 2016-09-23T07:52:42.000000           |
      | description                  | None                                 |
      | encrypted                    | False                                |
      | id                           | bab4b0e0-ce3d-4d57-bf57-3c51319f5202 |
      | metadata                     | {}                                   |
      | multiattach                  | False                                |
      | name                         | my-new-volume                        |
      | os-vol-tenant-attr:tenant_id | 3f670abbe9b34ca5b81db6e7b540b8d8     |
      | replication_status           | disabled                             |
      | size                         | 8                                    |
      | snapshot_id                  | None                                 |
      | source_volid                 | None                                 |
      | status                       | creating                             |
      | updated_at                   | None                                 |
      | user_id                      | fe19e3a9f63f4a14bd4697789247bbc5     |
      | volume_type                  | lvmdriver-1                          |
      +------------------------------+--------------------------------------+

#. To verify that your volume was created successfully, list the available
   volumes:

   .. code-block:: console

      $ openstack volume list
      +--------------------------------------+---------------+-----------+------+-------------+
      | ID                                   | DisplayName   |  Status   | Size | Attached to |
      +--------------------------------------+---------------+-----------+------+-------------+
      | bab4b0e0-ce3d-4d57-bf57-3c51319f5202 | my-new-volume | available | 8    |             |
      +--------------------------------------+---------------+-----------+------+-------------+


   If your volume was created successfully, its status is ``available``. If
   its status is ``error``, you might have exceeded your quota.

.. _Create_a_volume_from_specified_volume_type:

Create a volume from specified volume type
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Cinder supports these three ways to specify ``volume type`` during
volume creation.

#. volume_type
#. cinder_img_volume_type (via glance image metadata)
#. default_volume_type (via cinder.conf)

.. _volume_type:

volume_type
-----------

User can specify `volume type` when creating a volume.

.. code-block:: console

      $ openstack volume create -h -f {json,shell,table,value,yaml}
                               -c COLUMN --max-width <integer>
                               --noindent --prefix PREFIX --size <size>
                               --type <volume-type> --image <image>
                               --snapshot <snapshot> --source <volume>
                               --description <description> --user <user>
                               --project <project>
                               --availability-zone <availability-zone>
                               --property <key=value>
                               <name>


.. _cinder_img_volume_type:

cinder_img_volume_type
----------------------

If glance image has ``cinder_img_volume_type`` property, Cinder uses this
parameter to specify ``volume type`` when creating a volume.

Choose glance image which has ``cinder_img_volume_type`` property and create
a volume from the image.

.. code-block:: console

      $ openstack image list
      +----------------------------------+---------------------------------+--------+
      | ID                               | Name                            | Status |
      +----------------------------------+---------------------------------+--------+
      | 376bd633-c9c9-4c5d-a588-342f4f66 | cirros-0.3.5-x86_64-uec         | active |
      | d086                             |                                 |        |
      | 2c20fce7-2e68-45ee-ba8d-         | cirros-0.3.5-x86_64-uec-ramdisk | active |
      | beba27a91ab5                     |                                 |        |
      | a5752de4-9faf-4c47-acbc-         | cirros-0.3.5-x86_64-uec-kernel  | active |
      | 78a5efa7cc6e                     |                                 |        |
      +----------------------------------+---------------------------------+--------+


      $ openstack image show 376bd633-c9c9-4c5d-a588-342f4f66d086
      +------------------+-----------------------------------------------------------+
      | Field            | Value                                                     |
      +------------------+-----------------------------------------------------------+
      | checksum         | eb9139e4942121f22bbc2afc0400b2a4                          |
      | container_format | ami                                                       |
      | created_at       | 2016-10-13T03:28:55Z                                      |
      | disk_format      | ami                                                       |
      | file             | /v2/images/376bd633-c9c9-4c5d-a588-342f4f66d086/file      |
      | id               | 376bd633-c9c9-4c5d-a588-342f4f66d086                      |
      | min_disk         | 0                                                         |
      | min_ram          | 0                                                         |
      | name             | cirros-0.3.5-x86_64-uec                                   |
      | owner            | 88ba456e3a884c318394737765e0ef4d                          |
      | properties       | kernel_id='a5752de4-9faf-4c47-acbc-78a5efa7cc6e',         |
      |                  | ramdisk_id='2c20fce7-2e68-45ee-ba8d-beba27a91ab5'         |
      | protected        | False                                                     |
      | schema           | /v2/schemas/image                                         |
      | size             | 25165824                                                  |
      | status           | active                                                    |
      | tags             |                                                           |
      | updated_at       | 2016-10-13T03:28:55Z                                      |
      | virtual_size     | None                                                      |
      | visibility       | public                                                    |
      +------------------+-----------------------------------------------------------+

      $ openstack volume create --image 376bd633-c9c9-4c5d-a588-342f4f66d086 \
        --size 1 --availability-zone nova test
      +---------------------+--------------------------------------+
      | Field               | Value                                |
      +---------------------+--------------------------------------+
      | attachments         | []                                   |
      | availability_zone   | nova                                 |
      | bootable            | false                                |
      | consistencygroup_id | None                                 |
      | created_at          | 2016-10-13T06:29:53.688599           |
      | description         | None                                 |
      | encrypted           | False                                |
      | id                  | e6e6a72d-cda7-442c-830f-f306ea6a03d5 |
      | multiattach         | False                                |
      | name                | test                                 |
      | properties          |                                      |
      | replication_status  | disabled                             |
      | size                | 1                                    |
      | snapshot_id         | None                                 |
      | source_volid        | None                                 |
      | status              | creating                             |
      | type                | lvmdriver-1                          |
      | updated_at          | None                                 |
      | user_id             | 33fdc37314914796883706b33e587d51     |
      +---------------------+--------------------------------------+

.. _default_volume_type:

default_volume_type
-------------------

If above parameters are not set, Cinder uses default_volume_type which is
defined in cinder.conf during volume creation.

Example cinder.conf file configuration.

.. code-block:: console

   [default]
   default_volume_type = lvmdriver-1

.. _Attach_a_volume_to_an_instance:

Attach a volume to an instance
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

#. Attach your volume to a server, specifying the server ID and the volume
   ID:

   .. code-block:: console

      $ openstack server add volume 84c6e57d-a6b1-44b6-81eb-fcb36afd31b5 \
        573e024d-5235-49ce-8332-be1576d323f8 --device /dev/vdb

#. Show information for your volume:

   .. code-block:: console

      $ openstack volume show 573e024d-5235-49ce-8332-be1576d323f8

   The output shows that the volume is attached to the server with ID
   ``84c6e57d-a6b1-44b6-81eb-fcb36afd31b5``, is in the nova availability
   zone, and is bootable.

   .. code-block:: console

      +------------------------------+-----------------------------------------------+
      | Field                        | Value                                         |
      +------------------------------+-----------------------------------------------+
      | attachments                  | [{u'device': u'/dev/vdb',                     |
      |                              |        u'server_id': u'84c6e57d-a             |
      |                              |           u'id': u'573e024d-...               |
      |                              |        u'volume_id': u'573e024d...            |
      | availability_zone            | nova                                          |
      | bootable                     | true                                          |
      | consistencygroup_id          | None                                          |
      | created_at                   | 2016-10-13T06:08:07.000000                    |
      | description                  | None                                          |
      | encrypted                    | False                                         |
      | id                           | 573e024d-5235-49ce-8332-be1576d323f8          |
      | multiattach                  | False                                         |
      | name                         | my-new-volume                                 |
      | os-vol-tenant-attr:tenant_id | 7ef070d3fee24bdfae054c17ad742e28              |
      | properties                   |                                               |
      | replication_status           | disabled                                      |
      | size                         | 8                                             |
      | snapshot_id                  | None                                          |
      | source_volid                 | None                                          |
      | status                       | in-use                                        |
      | type                         | lvmdriver-1                                   |
      | updated_at                   | 2016-10-13T06:08:11.000000                    |
      | user_id                      | 33fdc37314914796883706b33e587d51              |
      | volume_image_metadata        |{u'kernel_id': u'df430cc2...,                  |
      |                              |        u'image_id': u'397e713c...,            |
      |                              |        u'ramdisk_id': u'3cf852bd...,          |
      |                              |u'image_name': u'cirros-0.3.5-x86_64-uec'}     |
      +------------------------------+-----------------------------------------------+



.. _Resize_a_volume:

Resize a volume
~~~~~~~~~~~~~~~

#. To resize your volume, you must first detach it from the server.
   To detach the volume from your server, pass the server ID and volume ID
   to the following command:

   .. code-block:: console

      $ openstack server remove volume 84c6e57d-a6b1-44b6-81eb-fcb36afd31b5 573e024d-5235-49ce-8332-be1576d323f8

   This command does not provide any output.

#. List volumes:

   .. code-block:: console

      $ openstack volume list
      +----------------+-----------------+-----------+------+-------------+
      |       ID       |   Display Name  |  Status   | Size | Attached to |
      +----------------+-----------------+-----------+------+-------------+
      | 573e024d-52... |  my-new-volume  | available |  8   |             |
      | bd7cf584-45... | my-bootable-vol | available |  8   |             |
      +----------------+-----------------+-----------+------+-------------+

   Note that the volume is now available.

#. Resize the volume by passing the volume ID and the new size (a value
   greater than the old one) as parameters:

   .. code-block:: console

      $ openstack volume set 573e024d-5235-49ce-8332-be1576d323f8 --size 10

   This command does not provide any output.

   .. note::

      When extending an LVM volume with a snapshot, the volume will be
      deactivated. The reactivation is automatic unless
      ``auto_activation_volume_list`` is defined in ``lvm.conf``. See
      ``lvm.conf`` for more information.

Delete a volume
~~~~~~~~~~~~~~~

#. To delete your volume, you must first detach it from the server.
   To detach the volume from your server and check for the list of existing
   volumes, see steps 1 and 2 in Resize_a_volume_.

   Delete the volume using either the volume name or ID:

   .. code-block:: console

      $ openstack volume delete my-new-volume

   This command does not provide any output.

#. List the volumes again, and note that the status of your volume is
   ``deleting``:

   .. code-block:: console

      $ openstack volume list
      +----------------+-----------------+-----------+------+-------------+
      |       ID       |   Display Name  |  Status   | Size | Attached to |
      +----------------+-----------------+-----------+------+-------------+
      | 573e024d-52... |  my-new-volume  |  deleting |  8   |             |
      | bd7cf584-45... | my-bootable-vol | available |  8   |             |
      +----------------+-----------------+-----------+------+-------------+

   When the volume is fully deleted, it disappears from the list of
   volumes:

   .. code-block:: console

      $ openstack volume list
      +----------------+-----------------+-----------+------+-------------+
      |       ID       |   Display Name  |  Status   | Size | Attached to |
      +----------------+-----------------+-----------+------+-------------+
      | bd7cf584-45... | my-bootable-vol | available |  8   |             |
      +----------------+-----------------+-----------+------+-------------+

Transfer a volume
~~~~~~~~~~~~~~~~~

You can transfer a volume from one owner to another by using the
:command:`openstack volume transfer request create` command. The volume
donor, or original owner, creates a transfer request and sends the created
transfer ID and authorization key to the volume recipient. The volume
recipient, or new owner, accepts the transfer by using the ID and key.

.. note::

   The procedure for volume transfer is intended for projects (both the
   volume donor and recipient) within the same cloud.

Use cases include:

*  Create a custom bootable volume or a volume with a large data set and
   transfer it to a customer.

*  For bulk import of data to the cloud, the data ingress system creates
   a new Block Storage volume, copies data from the physical device, and
   transfers device ownership to the end user.

Create a volume transfer request
--------------------------------

#. While logged in as the volume donor, list the available volumes:

   .. code-block:: console

      $ openstack volume list
      +-----------------+-----------------+-----------+------+-------------+
      |       ID        |   Display Name  |  Status   | Size | Attached to |
      +-----------------+-----------------+-----------+------+-------------+
      | 72bfce9f-cac... |       None      |   error   |  1   |             |
      | a1cdace0-08e... |       None      | available |  1   |             |
      +-----------------+-----------------+-----------+------+-------------+


#. As the volume donor, request a volume transfer authorization code for a
   specific volume:

   .. code-block:: console

      $ openstack volume transfer request create <volume>

    <volume>
       Name or ID of volume to transfer.

   The volume must be in an ``available`` state or the request will be
   denied. If the transfer request is valid in the database (that is, it
   has not expired or been deleted), the volume is placed in an
   ``awaiting-transfer`` state. For example:

   .. code-block:: console

      $ openstack volume transfer request create a1cdace0-08e4-4dc7-b9dc-457e9bcfe25f

   The output shows the volume transfer ID in the ``id`` row and the
   authorization key.

   .. code-block:: console

      +------------+--------------------------------------+
      | Field      | Value                                |
      +------------+--------------------------------------+
      | auth_key   | 0a59e53630f051e2                     |
      | created_at | 2016-11-03T11:49:40.346181           |
      | id         | 34e29364-142b-4c7b-8d98-88f765bf176f |
      | name       | None                                 |
      | volume_id  | a1cdace0-08e4-4dc7-b9dc-457e9bcfe25f |
      +------------+--------------------------------------+

   .. note::

      Optionally, you can specify a name for the transfer by using the
      ``--name transferName`` parameter.

   .. note::

      While the ``auth_key`` property is visible in the output of
      ``openstack volume transfer request create VOLUME_ID``, it will not be
      available in subsequent ``openstack volume transfer request show TRANSFER_ID``
      command.

#. Send the volume transfer ID and authorization key to the new owner (for
   example, by email).

#. View pending transfers:

   .. code-block:: console

      $ openstack volume transfer request list
      +--------------------------------------+--------------------------------------+------+
      |               ID                     |             Volume                   | Name |
      +--------------------------------------+--------------------------------------+------+
      | 6e4e9aa4-bed5-4f94-8f76-df43232f44dc | a1cdace0-08e4-4dc7-b9dc-457e9bcfe25f | None |
      +--------------------------------------+--------------------------------------+------+

#. After the volume recipient, or new owner, accepts the transfer, you can
   see that the transfer is no longer available:

   .. code-block:: console

      $ openstack volume transfer request list
      +----+-----------+------+
      | ID | Volume ID | Name |
      +----+-----------+------+
      +----+-----------+------+

Accept a volume transfer request
--------------------------------

#. As the volume recipient, you must first obtain the transfer ID and
   authorization key from the original owner.

#. Accept the request:

   .. code-block:: console

      $ openstack volume transfer request accept transferID authKey

   For example:

   .. code-block:: console

      $ openstack volume transfer request accept 6e4e9aa4-bed5-4f94-8f76-df43232f44dc b2c8e585cbc68a80
      +-----------+--------------------------------------+
      |  Property |                Value                 |
      +-----------+--------------------------------------+
      |     id    | 6e4e9aa4-bed5-4f94-8f76-df43232f44dc |
      |    name   |                 None                 |
      | volume_id | a1cdace0-08e4-4dc7-b9dc-457e9bcfe25f |
      +-----------+--------------------------------------+

   .. note::

      If you do not have a sufficient quota for the transfer, the transfer
      is refused.

Delete a volume transfer
------------------------

#. List available volumes and their statuses:

   .. code-block:: console

      $ openstack volume list
      +-----------------+-----------------+-----------------+------+-------------+
      |       ID        |   Display Name  |      Status     | Size | Attached to |
      +-----------------+-----------------+-----------------+------+-------------+
      | 72bfce9f-cac... |       None      |      error      |  1   |             |
      | a1cdace0-08e... |       None      |awaiting-transfer|  1   |             |
      +-----------------+-----------------+-----------------+------+-------------+


#. Find the matching transfer ID:

   .. code-block:: console

      $ openstack volume transfer request list
      +--------------------------------------+--------------------------------------+------+
      |               ID                     |             VolumeID                 | Name |
      +--------------------------------------+--------------------------------------+------+
      | a6da6888-7cdf-4291-9c08-8c1f22426b8a | a1cdace0-08e4-4dc7-b9dc-457e9bcfe25f | None |
      +--------------------------------------+--------------------------------------+------+

#. Delete the volume:

   .. code-block:: console

      $ openstack volume transfer request delete <transfer>

   <transfer>
      Name or ID of transfer to delete.

   For example:

   .. code-block:: console

      $ openstack volume transfer request delete a6da6888-7cdf-4291-9c08-8c1f22426b8a

#. Verify that transfer list is now empty and that the volume is again
   available for transfer:

   .. code-block:: console

      $ openstack volume transfer request list
      +----+-----------+------+
      | ID | Volume ID | Name |
      +----+-----------+------+
      +----+-----------+------+

   .. code-block:: console

      $ openstack volume list
      +-----------------+-----------+--------------+------+-------------+----------+-------------+
      |       ID        |   Status  | Display Name | Size | Volume Type | Bootable | Attached to |
      +-----------------+-----------+--------------+------+-------------+----------+-------------+
      | 72bfce9f-ca...  |   error   |     None     |  1   |     None    |  false   |             |
      | a1cdace0-08...  | available |     None     |  1   |     None    |  false   |             |
      +-----------------+-----------+--------------+------+-------------+----------+-------------+

Manage and unmanage a snapshot
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A snapshot is a point in time version of a volume. As an administrator,
you can manage and unmanage snapshots.

Manage a snapshot
-----------------

Manage a snapshot with the :command:`openstack volume snapshot set` command:

.. code-block:: console

   $ openstack volume snapshot set [-h]
                                   [--name <name>]
                                   [--description <description>]
                                   [--no-property]
                                   [--property <key=value>]
                                   [--state <state>]
                                   <snapshot>

The arguments to be passed are:

``--name <name>``
 New snapshot name

``--description <description>``
 New snapshot description

``--no-property``
 Remove all properties from <snapshot> (specify both
 --no-property and --property to remove the current
 properties before setting new properties.)

``--property <key=value>``
 Property to add or modify for this snapshot (repeat option to set
 multiple properties)

``--state <state>``
 New snapshot state. (“available”, “error”, “creating”, “deleting”,
 or “error_deleting”)
 (admin only) (This option simply changes the state of the snapshot in the
 database with no regard to actual status, exercise caution when using)

``<snapshot>``
 Snapshot to modify (name or ID)

.. code-block:: console

   $ openstack volume snapshot set my-snapshot-id

Unmanage a snapshot
-------------------

Unmanage a snapshot with the :command:`openstack volume snapshot unset`
command:

.. code-block:: console

   $ openstack volume snapshot unset [-h]
                                     [--property <key>]
                                     <snapshot>

The arguments to be passed are:

``--property <key>``
 Property to remove from snapshot (repeat option to remove multiple properties)

``<snapshot>``
 Snapshot to modify (name or ID).

The following example unmanages the ``my-snapshot-id`` image:

.. code-block:: console

   $ openstack volume snapshot unset my-snapshot-id
