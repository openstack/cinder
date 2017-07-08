==================
Consistency groups
==================

Consistency group support is available in OpenStack Block Storage. The
support is added for creating snapshots of consistency groups. This
feature leverages the storage level consistency technology. It allows
snapshots of multiple volumes in the same consistency group to be taken
at the same point-in-time to ensure data consistency. The consistency
group operations can be performed using the Block Storage command line.

.. note::

   Only Block Storage V2 API supports consistency groups. You can
   specify ``--os-volume-api-version 2`` when using Block Storage
   command line for consistency group operations.

Before using consistency groups, make sure the Block Storage driver that
you are running has consistency group support by reading the Block
Storage manual or consulting the driver maintainer. There are a small
number of drivers that have implemented this feature. The default LVM
driver does not support consistency groups yet because the consistency
technology is not available at the storage level.

Before using consistency groups, you must change policies for the
consistency group APIs in the ``/etc/cinder/policy.json`` file.
By default, the consistency group APIs are disabled.
Enable them before running consistency group operations.

Here are existing policy entries for consistency groups:

.. code-block:: json

   {
   "consistencygroup:create": "group:nobody"
   "consistencygroup:delete": "group:nobody",
   "consistencygroup:update": "group:nobody",
   "consistencygroup:get": "group:nobody",
   "consistencygroup:get_all": "group:nobody",
   "consistencygroup:create_cgsnapshot" : "group:nobody",
   "consistencygroup:delete_cgsnapshot": "group:nobody",
   "consistencygroup:get_cgsnapshot": "group:nobody",
   "consistencygroup:get_all_cgsnapshots": "group:nobody",
   }

Remove ``group:nobody`` to enable these APIs:

.. code-block:: json

   {
   "consistencygroup:create": "",
   "consistencygroup:delete": "",
   "consistencygroup:update": "",
   "consistencygroup:get": "",
   "consistencygroup:get_all": "",
   "consistencygroup:create_cgsnapshot" : "",
   "consistencygroup:delete_cgsnapshot": "",
   "consistencygroup:get_cgsnapshot": "",
   "consistencygroup:get_all_cgsnapshots": "",
   }


Restart Block Storage API service after changing policies.

The following consistency group operations are supported:

-  Create a consistency group, given volume types.

   .. note::

      A consistency group can support more than one volume type. The
      scheduler is responsible for finding a back end that can support
      all given volume types.

      A consistency group can only contain volumes hosted by the same
      back end.

      A consistency group is empty upon its creation. Volumes need to
      be created and added to it later.

-  Show a consistency group.

-  List consistency groups.

-  Create a volume and add it to a consistency group, given volume type
   and consistency group id.

-  Create a snapshot for a consistency group.

-  Show a snapshot of a consistency group.

-  List consistency group snapshots.

-  Delete a snapshot of a consistency group.

-  Delete a consistency group.

-  Modify a consistency group.

-  Create a consistency group from the snapshot of another consistency
   group.

-  Create a consistency group from a source consistency group.

The following operations are not allowed if a volume is in a consistency
group:

-  Volume migration.

-  Volume retype.

-  Volume deletion.

   .. note::

      A consistency group has to be deleted as a whole with all the
      volumes.

The following operations are not allowed if a volume snapshot is in a
consistency group snapshot:

-  Volume snapshot deletion.

   .. note::

      A consistency group snapshot has to be deleted as a whole with
      all the volume snapshots.

The details of consistency group operations are shown in the following.

.. note::

   Currently, no OpenStack client command is available to run in
   place of the cinder consistency group creation commands. Use the
   cinder commands detailed in the following examples.

**Create a consistency group**:

.. code-block:: console

   cinder consisgroup-create
   [--name name]
   [--description description]
   [--availability-zone availability-zone]
   volume-types

.. note::

   The parameter ``volume-types`` is required. It can be a list of
   names or UUIDs of volume types separated by commas without spaces in
   between. For example, ``volumetype1,volumetype2,volumetype3.``.

.. code-block:: console

   $ cinder consisgroup-create --name bronzeCG2 volume_type_1

   +-------------------+--------------------------------------+
   |      Property     |                Value                 |
   +-------------------+--------------------------------------+
   | availability_zone |                 nova                 |
   |     created_at    |      2014-12-29T12:59:08.000000      |
   |    description    |                 None                 |
   |         id        | 1de80c27-3b2f-47a6-91a7-e867cbe36462 |
   |        name       |              bronzeCG2               |
   |       status      |               creating               |
   +-------------------+--------------------------------------+

**Show a consistency group**:

.. code-block:: console

   $ cinder consisgroup-show 1de80c27-3b2f-47a6-91a7-e867cbe36462

   +-------------------+--------------------------------------+
   |      Property     |                Value                 |
   +-------------------+--------------------------------------+
   | availability_zone |                 nova                 |
   |     created_at    |      2014-12-29T12:59:08.000000      |
   |    description    |                 None                 |
   |         id        | 2a6b2bda-1f43-42ce-9de8-249fa5cbae9a |
   |        name       |              bronzeCG2               |
   |       status      |              available               |
   |     volume_types  |              volume_type_1           |
   +-------------------+--------------------------------------+

**List consistency groups**:

.. code-block:: console

   $ cinder consisgroup-list

   +--------------------------------------+-----------+-----------+
   |                  ID                  |   Status  |    Name   |
   +--------------------------------------+-----------+-----------+
   | 1de80c27-3b2f-47a6-91a7-e867cbe36462 | available | bronzeCG2 |
   | 3a2b3c42-b612-479a-91eb-1ed45b7f2ad5 |   error   |  bronzeCG |
   +--------------------------------------+-----------+-----------+

**Create a volume and add it to a consistency group**:

.. note::

   When creating a volume and adding it to a consistency group, a
   volume type and a consistency group id must be provided. This is
   because a consistency group can support more than one volume type.

.. code-block:: console

   $ openstack volume create --type volume_type_1 --consistency-group \
     1de80c27-3b2f-47a6-91a7-e867cbe36462 --size 1 cgBronzeVol

   +---------------------------------------+--------------------------------------+
   | Field                                 | Value                                |
   +---------------------------------------+--------------------------------------+
   |              attachments              |                  []                  |
   |           availability_zone           |                 nova                 |
   |                bootable               |                false                 |
   |          consistencygroup_id          | 1de80c27-3b2f-47a6-91a7-e867cbe36462 |
   |               created_at              |      2014-12-29T13:16:47.000000      |
   |              description              |                 None                 |
   |               encrypted               |                False                 |
   |                   id                  | 5e6d1386-4592-489f-a56b-9394a81145fe |
   |                metadata               |                  {}                  |
   |                  name                 |             cgBronzeVol              |
   |         os-vol-host-attr:host         |      server-1@backend-1#pool-1       |
   |     os-vol-mig-status-attr:migstat    |                 None                 |
   |     os-vol-mig-status-attr:name_id    |                 None                 |
   |      os-vol-tenant-attr:tenant_id     |   1349b21da2a046d8aa5379f0ed447bed   |
   |   os-volume-replication:driver_data   |                 None                 |
   | os-volume-replication:extended_status |                 None                 |
   |           replication_status          |               disabled               |
   |                  size                 |                  1                   |
   |              snapshot_id              |                 None                 |
   |              source_volid             |                 None                 |
   |                 status                |               creating               |
   |                user_id                |   93bdea12d3e04c4b86f9a9f172359859   |
   |              volume_type              |            volume_type_1             |
   +---------------------------------------+--------------------------------------+

**Create a snapshot for a consistency group**:

.. code-block:: console

   $ cinder cgsnapshot-create 1de80c27-3b2f-47a6-91a7-e867cbe36462

   +---------------------+--------------------------------------+
   |       Property      |                Value                 |
   +---------------------+--------------------------------------+
   | consistencygroup_id | 1de80c27-3b2f-47a6-91a7-e867cbe36462 |
   |      created_at     |      2014-12-29T13:19:44.000000      |
   |     description     |                 None                 |
   |          id         | d4aff465-f50c-40b3-b088-83feb9b349e9 |
   |         name        |                 None                 |
   |        status       |               creating               |
   +---------------------+-------------------------------------+

**Show a snapshot of a consistency group**:

.. code-block:: console

   $ cinder cgsnapshot-show d4aff465-f50c-40b3-b088-83feb9b349e9

**List consistency group snapshots**:

.. code-block:: console

   $ cinder cgsnapshot-list

   +--------------------------------------+--------+----------+
   |                  ID                  | Status | Name     |
   +--------------------------------------+--------+----------+
   | 6d9dfb7d-079a-471e-b75a-6e9185ba0c38 | available  | None |
   | aa129f4d-d37c-4b97-9e2d-7efffda29de0 | available  | None |
   | bb5b5d82-f380-4a32-b469-3ba2e299712c | available  | None |
   | d4aff465-f50c-40b3-b088-83feb9b349e9 | available  | None |
   +--------------------------------------+--------+----------+

**Delete a snapshot of a consistency group**:

.. code-block:: console

   $ cinder cgsnapshot-delete d4aff465-f50c-40b3-b088-83feb9b349e9

**Delete a consistency group**:

.. note::

   The force flag is needed when there are volumes in the consistency
   group:

   .. code-block:: console

      $ cinder consisgroup-delete --force 1de80c27-3b2f-47a6-91a7-e867cbe36462

**Modify a consistency group**:

.. code-block:: console

   cinder consisgroup-update
   [--name NAME]
   [--description DESCRIPTION]
   [--add-volumes UUID1,UUID2,......]
   [--remove-volumes UUID3,UUID4,......]
   CG

The parameter ``CG`` is required. It can be a name or UUID of a consistency
group. UUID1,UUID2,...... are UUIDs of one or more volumes to be added
to the consistency group, separated by commas. Default is None.
UUID3,UUID4,...... are UUIDs of one or more volumes to be removed from
the consistency group, separated by commas. Default is None.

.. code-block:: console

   $ cinder consisgroup-update --name 'new name' \
     --description 'new description' \
     --add-volumes 0b3923f5-95a4-4596-a536-914c2c84e2db,1c02528b-3781-4e32-929c-618d81f52cf3 \
     --remove-volumes 8c0f6ae4-efb1-458f-a8fc-9da2afcc5fb1,a245423f-bb99-4f94-8c8c-02806f9246d8 \
     1de80c27-3b2f-47a6-91a7-e867cbe36462

**Create a consistency group from the snapshot of another consistency
group**:

.. code-block:: console

   $ cinder consisgroup-create-from-src
   [--cgsnapshot CGSNAPSHOT]
   [--name NAME]
   [--description DESCRIPTION]

The parameter ``CGSNAPSHOT`` is a name or UUID of a snapshot of a
consistency group:

.. code-block:: console

   $ cinder consisgroup-create-from-src \
     --cgsnapshot 6d9dfb7d-079a-471e-b75a-6e9185ba0c38 \
     --name 'new cg' --description 'new cg from cgsnapshot'

**Create a consistency group from a source consistency group**:

.. code-block:: console

   $ cinder consisgroup-create-from-src
   [--source-cg SOURCECG]
   [--name NAME]
   [--description DESCRIPTION]

The parameter ``SOURCECG`` is a name or UUID of a source
consistency group:

.. code-block:: console

   $ cinder consisgroup-create-from-src \
     --source-cg 6d9dfb7d-079a-471e-b75a-6e9185ba0c38 \
     --name 'new cg' --description 'new cloned cg'
