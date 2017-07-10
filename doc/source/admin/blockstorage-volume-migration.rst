.. _volume_migration.rst:

===============
Migrate volumes
===============

OpenStack has the ability to migrate volumes between back ends which support
its volume-type. Migrating a volume transparently moves its data from the
current back end for the volume to a new one. This is an administrator
function, and can be used for functions including storage evacuation (for
maintenance or decommissioning), or manual optimizations (for example,
performance, reliability, or cost).

These workflows are possible for a migration:

#. If the storage can migrate the volume on its own, it is given the
   opportunity to do so. This allows the Block Storage driver to enable
   optimizations that the storage might be able to perform. If the back end
   is not able to perform the migration, the Block Storage uses one of two
   generic flows, as follows.

#. If the volume is not attached, the Block Storage service creates a volume
   and copies the data from the original to the new volume.

   .. note::

      While most back ends support this function, not all do. See the `driver
      documentation <https://docs.openstack.org/ocata/config-reference/block-storage/volume-drivers.html>`__
      in the OpenStack Configuration Reference for more details.

#. If the volume is attached to a VM instance, the Block Storage creates a
   volume, and calls Compute to copy the data from the original to the new
   volume. Currently this is supported only by the Compute libvirt driver.

As an example, this scenario shows two LVM back ends and migrates an attached
volume from one to the other. This scenario uses the third migration flow.

First, list the available back ends:

.. code-block:: console

   # cinder get-pools
   +----------+----------------------------------------------------+
   | Property |                       Value                        |
   +----------+----------------------------------------------------+
   |   name   |           server1@lvmstorage-1#lvmstorage-1        |
   +----------+----------------------------------------------------+
   +----------+----------------------------------------------------+
   | Property |                      Value                         |
   +----------+----------------------------------------------------+
   |   name   |           server2@lvmstorage-2#lvmstorage-2        |
   +----------+----------------------------------------------------+

.. note::

   Only Block Storage V2 API supports :command:`cinder get-pools`.

You can also get available back ends like following:

.. code-block:: console

   # cinder-manage host list
   server1@lvmstorage-1    zone1
   server2@lvmstorage-2    zone1

But it needs to add pool name in the end. For example,
``server1@lvmstorage-1#zone1``.

Next, as the admin user, you can see the current status of the volume
(replace the example ID with your own):

.. code-block:: console

   $ openstack volume show 6088f80a-f116-4331-ad48-9afb0dfb196c

   +--------------------------------+--------------------------------------+
   | Field                          | Value                                |
   +--------------------------------+--------------------------------------+
   | attachments                    | []                                   |
   | availability_zone              | zone1                                |
   | bootable                       | false                                |
   | consistencygroup_id            | None                                 |
   | created_at                     | 2013-09-01T14:53:22.000000           |
   | description                    | test                                 |
   | encrypted                      | False                                |
   | id                             | 6088f80a-f116-4331-ad48-9afb0dfb196c |
   | migration_status               | None                                 |
   | multiattach                    | False                                |
   | name                           | test                                 |
   | os-vol-host-attr:host          | server1@lvmstorage-1#lvmstorage-1    |
   | os-vol-mig-status-attr:migstat | None                                 |
   | os-vol-mig-status-attr:name_id | None                                 |
   | os-vol-tenant-attr:tenant_id   | d88310717a8e4ebcae84ed075f82c51e     |
   | properties                     | readonly='False'                     |
   | replication_status             | disabled                             |
   | size                           | 1                                    |
   | snapshot_id                    | None                                 |
   | source_volid                   | None                                 |
   | status                         | in-use                               |
   | type                           | None                                 |
   | updated_at                     | 2016-07-31T07:22:19.000000           |
   | user_id                        | d8e5e5727f3a4ce1886ac8ecec058e83     |
   +--------------------------------+--------------------------------------+

Note these attributes:

* ``os-vol-host-attr:host`` - the volume's current back end.
* ``os-vol-mig-status-attr:migstat`` - the status of this volume's migration
  (None means that a migration is not currently in progress).
* ``os-vol-mig-status-attr:name_id`` - the volume ID that this volume's name
  on the back end is based on. Before a volume is ever migrated, its name on
  the back end storage may be based on the volume's ID (see the
  ``volume_name_template`` configuration parameter). For example, if
  ``volume_name_template`` is kept as the default value (``volume-%s``), your
  first LVM back end has a logical volume named
  ``volume-6088f80a-f116-4331-ad48-9afb0dfb196c``. During the course of a
  migration, if you create a volume and copy over the data, the volume get
  the new name but keeps its original ID. This is exposed by the ``name_id``
  attribute.

  .. note::

     If you plan to decommission a block storage node, you must stop the
     ``cinder`` volume service on the node after performing the migration.

     On nodes that run CentOS, Fedora, openSUSE, Red Hat Enterprise Linux,
     or SUSE Linux Enterprise, run:

     .. code-block:: console

        # service openstack-cinder-volume stop
        # chkconfig openstack-cinder-volume off

     On nodes that run Ubuntu or Debian, run:

     .. code-block:: console

        # service cinder-volume stop
        # chkconfig cinder-volume off

     Stopping the cinder volume service will prevent volumes from being
     allocated to the node.

Migrate this volume to the second LVM back end:

.. code-block:: console

   $ cinder migrate 6088f80a-f116-4331-ad48-9afb0dfb196c \
     server2@lvmstorage-2#lvmstorage-2

   Request to migrate volume 6088f80a-f116-4331-ad48-9afb0dfb196c has been
   accepted.

You can use the :command:`openstack volume show` command to see the status of
the migration. While migrating, the ``migstat`` attribute shows states such as
``migrating`` or ``completing``. On error, ``migstat`` is set to None and the
host attribute shows the original ``host``. On success, in this example, the
output looks like:

.. code-block:: console

   $ openstack volume show 6088f80a-f116-4331-ad48-9afb0dfb196c

   +--------------------------------+--------------------------------------+
   | Field                          | Value                                |
   +--------------------------------+--------------------------------------+
   | attachments                    | []                                   |
   | availability_zone              | zone1                                |
   | bootable                       | false                                |
   | consistencygroup_id            | None                                 |
   | created_at                     | 2013-09-01T14:53:22.000000           |
   | description                    | test                                 |
   | encrypted                      | False                                |
   | id                             | 6088f80a-f116-4331-ad48-9afb0dfb196c |
   | migration_status               | None                                 |
   | multiattach                    | False                                |
   | name                           | test                                 |
   | os-vol-host-attr:host          | server2@lvmstorage-2#lvmstorage-2    |
   | os-vol-mig-status-attr:migstat | completing                           |
   | os-vol-mig-status-attr:name_id | None                                 |
   | os-vol-tenant-attr:tenant_id   | d88310717a8e4ebcae84ed075f82c51e     |
   | properties                     | readonly='False'                     |
   | replication_status             | disabled                             |
   | size                           | 1                                    |
   | snapshot_id                    | None                                 |
   | source_volid                   | None                                 |
   | status                         | in-use                               |
   | type                           | None                                 |
   | updated_at                     | 2017-02-22T02:35:03.000000           |
   | user_id                        | d8e5e5727f3a4ce1886ac8ecec058e83     |
   +--------------------------------+--------------------------------------+

Note that ``migstat`` is None, host is the new host, and ``name_id`` holds the
ID of the volume created by the migration. If you look at the second LVM back
end, you find the logical volume
``volume-133d1f56-9ffc-4f57-8798-d5217d851862``.

.. note::

   The migration is not visible to non-admin users (for example, through the
   volume ``status``). However, some operations are not allowed while a
   migration is taking place, such as attaching/detaching a volume and
   deleting a volume. If a user performs such an action during a migration,
   an error is returned.

.. note::

   Migrating volumes that have snapshots are currently not allowed.
