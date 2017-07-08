=====================
Generic volume groups
=====================

Generic volume group support is available in OpenStack Block Storage (cinder)
since the Newton release. The support is added for creating group types and
group specs, creating groups of volumes, and creating snapshots of groups.
The group operations can be performed using the Block Storage command line.

A group type is a type for a group just like a volume type for a volume.
A group type can also have associated group specs similar to extra specs
for a volume type.

In cinder, there is a group construct called `consistency group`. Consistency
groups only support consistent group snapshots and only a small number of
drivers can support it. The following is a list of drivers that support
consistency groups and the release when the support was added:

- Juno: EMC VNX

- Kilo: EMC VMAX, IBM (GPFS, Storwize, SVC, and XIV), ProphetStor, Pure

- Liberty: Dell Storage Center, EMC XtremIO, HPE 3Par and LeftHand

- Mitaka: EMC ScaleIO, NetApp Data ONTAP and E-Series, SolidFire

- Newton: CoprHD, FalconStor, Huawei

Consistency group cannot be extended easily to serve other purposes. A tenant
may want to put volumes used in the same application together in a group so
that it is easier to manage them together, and this group of volumes may or
may not support consistent group snapshot. Generic volume group is introduced
to solve this problem.

There is a plan to migrate existing consistency group operations to use
generic volume group operations in future releases. More information can be
found in `Cinder specs <https://github.com/openstack/cinder-specs/blob/master/specs/newton/group-snapshots.rst>`_.

.. note::

   Only Block Storage V3 API supports groups. You can
   specify ``--os-volume-api-version 3.x`` when using the `cinder`
   command line for group operations where `3.x` contains a microversion value
   for that command. The generic volume group feature was completed in several
   patches. As a result, the minimum required microversion is different for
   group types, groups, and group snapshots APIs.

The following group type operations are supported:

-  Create a group type.

-  Delete a group type.

-  Set group spec for a group type.

-  Unset group spec for a group type.

-  List group types.

-  Show a group type details.

-  Update a group.

-  List group types and group specs.

The following group and group snapshot operations are supported:

-  Create a group, given group type and volume types.

   .. note::

      A group must have one group type. A group can support more than one
      volume type. The scheduler is responsible for finding a back end that
      can support the given group type and volume types.

      A group can only contain volumes hosted by the same back end.

      A group is empty upon its creation. Volumes need to be created and added
      to it later.

-  Show a group.

-  List groups.

-  Delete a group.

-  Modify a group.

-  Create a volume and add it to a group.

-  Create a snapshot for a group.

-  Show a group snapshot.

-  List group snapshots.

-  Delete a group snapshot.

-  Create a group from a group snapshot.

-  Create a group from a source group.

The following operations are not allowed if a volume is in a group:

-  Volume migration.

-  Volume retype.

-  Volume deletion.

   .. note::

      A group has to be deleted as a whole with all the volumes.

The following operations are not allowed if a volume snapshot is in a
group snapshot:

-  Volume snapshot deletion.

   .. note::

      A group snapshot has to be deleted as a whole with all the volume
      snapshots.

The details of group type operations are shown in the following. The minimum
microversion to support group type and group specs is 3.11:

**Create a group type**:

.. code-block:: console

   cinder --os-volume-api-version 3.11 group-type-create
   [--description DESCRIPTION]
   [--is-public IS_PUBLIC]
   NAME

.. note::

   The parameter ``NAME`` is required. The
   ``--is-public IS_PUBLIC`` determines whether the group type is
   accessible to the public. It is ``True`` by default. By default, the
   policy on privileges for creating a group type is admin-only.

**Show a group type**:

.. code-block:: console

   cinder --os-volume-api-version 3.11 group-type-show
   GROUP_TYPE

.. note::

   The parameter ``GROUP_TYPE`` is the name or UUID of a group type.

**List group types**:

.. code-block:: console

   cinder --os-volume-api-version 3.11 group-type-list

.. note::

   Only admin can see private group types.

**Update a group type**:

.. code-block:: console

   cinder --os-volume-api-version 3.11 group-type-update
   [--name NAME]
   [--description DESCRIPTION]
   [--is-public IS_PUBLIC]
   GROUP_TYPE_ID

.. note::

   The parameter ``GROUP_TYPE_ID`` is the UUID of a group type. By default,
   the policy on privileges for updating a group type is admin-only.

**Delete group type or types**:

.. code-block:: console

   cinder --os-volume-api-version 3.11 group-type-delete
   GROUP_TYPE [GROUP_TYPE ...]

.. note::

   The parameter ``GROUP_TYPE`` is name or UUID of the group type or
   group types to be deleted. By default, the policy on privileges for
   deleting a group type is admin-only.

**Set or unset group spec for a group type**:

.. code-block:: console

   cinder --os-volume-api-version 3.11 group-type-key
   GROUP_TYPE ACTION KEY=VALUE [KEY=VALUE ...]

.. note::

   The parameter ``GROUP_TYPE`` is the name or UUID of a group type. Valid
   values for the parameter ``ACTION`` are ``set`` or ``unset``.
   ``KEY=VALUE`` is the group specs key and value pair to set or unset.
   For unset, specify only the key. By default, the policy on privileges
   for setting or unsetting group specs key is admin-only.

**List group types and group specs**:

.. code-block:: console

   cinder --os-volume-api-version 3.11 group-specs-list

.. note::

   By default, the policy on privileges for seeing group specs is admin-only.

The details of group operations are shown in the following. The minimum
microversion to support groups operations is 3.13.

**Create a group**:

.. code-block:: console

   cinder --os-volume-api-version 3.13 group-create
   [--name NAME]
   [--description DESCRIPTION]
   [--availability-zone AVAILABILITY_ZONE]
   GROUP_TYPE VOLUME_TYPES

.. note::

   The parameters ``GROUP_TYPE`` and ``VOLUME_TYPES`` are required.
   ``GROUP_TYPE`` is the name or UUID of a group type. ``VOLUME_TYPES``
   can be a list of names or UUIDs of volume types separated by commas
   without spaces in between. For example,
   ``volumetype1,volumetype2,volumetype3.``.

**Show a group**:

.. code-block:: console

   cinder --os-volume-api-version 3.13 group-show
   GROUP

.. note::

   The parameter ``GROUP`` is the name or UUID of a group.

**List groups**:

.. code-block:: console

   cinder --os-volume-api-version 3.13 group-list
   [--all-tenants [<0|1>]]

.. note::

   ``--all-tenants`` specifies whether to list groups for all tenants.
   Only admin can use this option.

**Create a volume and add it to a group**:

.. code-block:: console

   cinder --os-volume-api-version 3.13 create
   --volume-type VOLUME_TYPE
   --group-id GROUP_ID SIZE

.. note::

   When creating a volume and adding it to a group, the parameters
   ``VOLUME_TYPE`` and ``GROUP_ID`` must be provided. This is because a group
   can support more than one volume type.

**Delete a group**:

.. code-block:: console

   cinder --os-volume-api-version 3.13 group-delete
   [--delete-volumes]
   GROUP [GROUP ...]

.. note::

   ``--delete-volumes`` allows or disallows groups to be deleted
   if they are not empty. If the group is empty, it can be deleted without
   ``--delete-volumes``. If the group is not empty, the flag is
   required for it to be deleted. When the flag is specified, the group
   and all volumes in the group will be deleted.

**Modify a group**:

.. code-block:: console

   cinder --os-volume-api-version 3.13 group-update
   [--name NAME]
   [--description DESCRIPTION]
   [--add-volumes UUID1,UUID2,......]
   [--remove-volumes UUID3,UUID4,......]
   GROUP

.. note::

   The parameter ``UUID1,UUID2,......`` is the UUID of one or more volumes
   to be added to the group, separated by commas. Similarly the parameter
   ``UUID3,UUID4,......`` is the UUID of one or more volumes to be removed
   from the group, separated by commas.

The details of group snapshots operations are shown in the following. The
minimum microversion to support group snapshots operations is 3.14.

**Create a snapshot for a group**:

.. code-block:: console

   cinder --os-volume-api-version 3.14 group-snapshot-create
   [--name NAME]
   [--description DESCRIPTION]
   GROUP

.. note::

   The parameter ``GROUP`` is the name or UUID of a group.

**Show a group snapshot**:

.. code-block:: console

   cinder --os-volume-api-version 3.14 group-snapshot-show
   GROUP_SNAPSHOT

.. note::

   The parameter ``GROUP_SNAPSHOT`` is the name or UUID of a group snapshot.

**List group snapshots**:

.. code-block:: console

   cinder --os-volume-api-version 3.14 group-snapshot-list
   [--all-tenants [<0|1>]]
   [--status STATUS]
   [--group-id GROUP_ID]

.. note::

   ``--all-tenants`` specifies whether to list group snapshots for
   all tenants. Only admin can use this option. ``--status STATUS``
   filters results by a status. ``--group-id GROUP_ID`` filters
   results by a group id.

**Delete group snapshot**:

.. code-block:: console

   cinder --os-volume-api-version 3.14 group-snapshot-delete
   GROUP_SNAPSHOT [GROUP_SNAPSHOT ...]

.. note::

   The parameter ``GROUP_SNAPSHOT`` specifies the name or UUID of one or more
   group snapshots to be deleted.

**Create a group from a group snapshot or a source group**:

.. code-block:: console

   $ cinder --os-volume-api-version 3.14 group-create-from-src
   [--group-snapshot GROUP_SNAPSHOT]
   [--source-group SOURCE_GROUP]
   [--name NAME]
   [--description DESCRIPTION]

.. note::

   The parameter ``GROUP_SNAPSHOT`` is a name or UUID of a group snapshot.
   The parameter ``SOURCE_GROUP`` is a name or UUID of a source group.
   Either ``GROUP_SNAPSHOT`` or ``SOURCE_GROUP`` must be specified, but not
   both.
