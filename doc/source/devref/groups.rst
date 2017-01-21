Generic Volume Groups
=====================

Introduction to generic volume groups
-------------------------------------

Generic volume group support was added in cinder in the Newton release.
There is support for creating group types and group specs, creating
groups of volumes, and creating snapshots of groups. Detailed information
on how to create a group type, a group, and a group snapshot can be found
in `block storage admin guide <http://docs.openstack.org/admin-guide/blockstorage-groups.html>`_.

How is generic volume groups different from consistency groups in cinder?
The consistency group feature was introduced in cinder in Juno and are
supported by a few drivers. Currently consistency groups in cinder only
support consistent group snapshot. It cannot be extended easily to serve
other purposes. A tenant may want to put volumes used in the same application
together in a group so that it is easier to manage them together, and this
group of volumes may or may not support consistent group snapshot. Generic
volume group is introduced to solve this problem. By decoupling the tight
relationship between the group construct and the consistency concept,
generic volume groups can be extended to support other features in the future.

Action items for drivers supporting consistency groups
------------------------------------------------------

Drivers currently supporting consistency groups are in the following:

- Juno: EMC VNX

- Kilo: EMC VMAX, IBM (GPFS, Storwize, SVC, and XIV), ProphetStor, Pure

- Liberty: Dell Storage Center, EMC XtremIO, HPE 3Par and LeftHand

- Mitaka: EMC ScaleIO, NetApp Data ONTAP and E-Series, SolidFire

- Newton: CoprHD, FalconStor, Huawei

Since the addition of generic volume groups, there is plan to migrate
consistency groups to generic volume groups. A migration command and
changes in CG APIs to support migrating CGs to groups are developed and
merged in Ocata [1][2]. In order to support rolling upgrade, it will take
a couple of releases before consistency groups can be deprecated.

For drivers planning to add consistency groups support, the new generic
volume group driver interfaces should be implemented instead of the CG
interfaces.

For drivers already supporting consistency groups, the new generic
volume group driver interfaces should be implemented to include the
CG support.

For drivers wanting generic volume groups but not consistent group
snapshot support, no code changes are necessary. By default, every
cinder volume driver already supports generic volume groups since
Newton because the support was added to the common code. Testing
should be done for every driver to make sure this feature works properly.

Drivers already supporting CG are expected to add CG support to
generic volume groups by Pike-1. This is a deadline discussed and
agreed upon at the Ocata summit in Barcelona.

Group Type and Group Specs / Volume Types and Extra Specs
---------------------------------------------------------

The driver interfaces for consistency groups and generic volume groups
are very similar. One new concept introduced for generic volume groups
is the group type. Group type is used to categorize a group just like a
volume type is used to describe a volume. Similar to extra specs for
a volume type, group specs are also introduced to be associated with a
group type. Group types allow a user to create different types of groups.

A group can support multiple volume types and volume types are required
as input parameters when creating a group. In addition to volume types,
a group type is also required when creating a group.

Group types and volume types are created by the Cloud Administrator.
A tenant uses the group types and volume types to create groups and
volumes.

A driver can support both consistent group snapshot and a group of
snapshots that do not maintain the write order consistency by using
different group types. In other words, a group supporting consistent
group snapshot is a special type of generic volume group.

For a group to support consistent group snapshot, the group specs in the
corresponding group type should have the following entry::

    {'consistent_group_snapshot_enabled': <is> True}

Similarly, for a volume to be in a group that supports consistent group
snapshots, the volume type extra specs would also have the following entry::

    {'consistent_group_snapshot_enabled': <is> True}

By requiring the above entry to be in both group specs and volume type
extra specs, we can make sure the scheduler will choose a backend that
supports the group type and volume types for a group. It is up to the driver
to parse the group type info when creating a group, parse the volume type
info when creating a volume, and set things up as requested.

Capabilities reporting
----------------------
The following entry is expected to be added to the stats/capabilities update
for drivers supporting consistent group snapshot::

    stats["consistent_group_snapshot_enabled"] = True

Driver methods
--------------
The following driver methods should to be implemented for the driver to
support consistent group snapshot:

- create_group(context, group)

- delete_group(context, group, volumes)

- update_group(context, group, add_volumes=None, remove_volumes=None)

- create_group_from_src(context, group, volumes,
                        group_snapshot=None, snapshots=None,
                        source_group=None, source_vols=None)

- create_group_snapshot(context, group_snapshot, snapshots)

- delete_group_snapshot(context, group_snapshot, snapshots)

Here is an example that add CG capability to generic volume groups [3].
Details of driver interfaces are as follows.

**create_group**

This method creates a group. It has context and group object as input
parameters. A group object has volume_types and group_type_id that can be used
by the driver.

create_group returns model_update. model_update will be in this format:
{'status': xxx, ......}.

If the status in model_update is 'error', the manager will throw
an exception and it will be caught in the try-except block in the
manager. If the driver throws an exception, the manager will also
catch it in the try-except block. The group status in the db will
be changed to 'error'.

For a successful operation, the driver can either build the
model_update and return it or return None. The group status will
be set to 'available'.

**delete_group**

This method deletes a group. It has context, group object, and a list
of volume objects as input parameters. It returns model_update and
volumes_model_update.

volumes_model_update is a list of volume dictionaries. It has to be built
by the driver. An entry will be in this format: {'id': xxx, 'status': xxx,
......}. model_update will be in this format: {'status': xxx, ......}.
The driver should populate volumes_model_update and model_update
and return them.

The manager will check volumes_model_update and update db accordingly
for each volume. If the driver successfully deleted some volumes
but failed to delete others, it should set statuses of the volumes
accordingly so that the manager can update db correctly.

If the status in any entry of volumes_model_update is 'error_deleting'
or 'error', the status in model_update will be set to the same if it
is not already 'error_deleting' or 'error'.

If the status in model_update is 'error_deleting' or 'error', the
manager will raise an exception and the status of the group will be
set to 'error' in the db. If volumes_model_update is not returned by
the driver, the manager will set the status of every volume in the
group to 'error' in the except block.

If the driver raises an exception during the operation, it will be
caught by the try-except block in the manager. The statuses of the
group and all volumes in it will be set to 'error'.

For a successful operation, the driver can either build the
model_update and volumes_model_update and return them or
return None, None. The statuses of the group and all volumes
will be set to 'deleted' after the manager deletes them from db.

**update_group**

This method adds existing volumes to a group or removes volumes
from a group. It has context, group object, a list of volume objects
to be added to the group, and a list of a volume objects to be
removed from the group. It returns model_update, add_volumes_update,
and remove_volumes_update.

model_update is a dictionary that the driver wants the manager
to update upon a successful return. If None is returned, the manager
will set the status to 'available'.

add_volumes_update and remove_volumes_update are lists of dictionaries
that the driver wants the manager to update upon a successful return.
Note that each entry requires a {'id': xxx} so that the correct
volume entry can be updated. If None is returned, the volume will
remain its original status.

If the driver throws an exception, the status of the group as well as
those of the volumes to be added/removed will be set to 'error'.

**create_group_from_src**

This method creates a group from source. The source can be a
group_snapshot or a source group. create_group_from_src has context,
group object, a list of volume objects, group_snapshot object, a list
of snapshot objects, source group object, and a list of source volume
objects as input parameters. It returns model_update and
volumes_model_update.

volumes_model_update is a list of dictionaries. It has to be built by
the driver. An entry will be in this format: {'id': xxx, 'status': xxx,
......}. model_update will be in this format: {'status': xxx, ......}.

To be consistent with other volume operations, the manager will
assume the operation is successful if no exception is thrown by
the driver. For a successful operation, the driver can either build
the model_update and volumes_model_update and return them or
return None, None.

**create_group_snapshot**

This method creates a group_snapshot. It has context, group_snapshot
object, and a list of snapshot objects as input parameters. It returns
model_update and snapshots_model_update.

snapshots_model_update is a list of dictionaries. It has to be built by the
driver. An entry will be in this format: {'id': xxx, 'status': xxx, ......}.
model_update will be in this format: {'status': xxx, ......}. The driver
should populate snapshots_model_update and model_update and return them.

The manager will check snapshots_model_update and update db accordingly
for each snapshot. If the driver successfully created some snapshots
but failed to create others, it should set statuses of the snapshots
accordingly so that the manager can update db correctly.

If the status in any entry of snapshots_model_update is 'error', the
status in model_update will be set to the same if it is not already
'error'.

If the status in model_update is 'error', the manager will raise an
exception and the status of group_snapshot will be set to 'error' in
the db. If snapshots_model_update is not returned by the driver, the
manager will set the status of every snapshot to 'error' in the except
block.

If the driver raises an exception during the operation, it will be
caught by the try-except block in the manager and the statuses of
group_snapshot and all snapshots will be set to 'error'.

For a successful operation, the driver can either build the
model_update and snapshots_model_update and return them or
return None, None. The statuses of group_snapshot and all snapshots
will be set to 'available' at the end of the manager function.

**delete_group_snapshot**

This method deletes a group_snapshot. It has context, group_snapshot
object, and a list of snapshot objects. It returns model_update and
snapshots_model_update.

snapshots_model_update is a list of dictionaries. It has to be built by
the driver. An entry will be in this format: {'id': xxx, 'status': xxx,
......}. model_update will be in this format: {'status': xxx, ......}.
The driver should populate snapshots_model_update and model_update
and return them.

The manager will check snapshots_model_update and update db accordingly
for each snapshot. If the driver successfully deleted some snapshots
but failed to delete others, it should set statuses of the snapshots
accordingly so that the manager can update db correctly.

If the status in any entry of snapshots_model_update is
'error_deleting' or 'error', the status in model_update will be set to
the same if it is not already 'error_deleting' or 'error'.

If the status in model_update is 'error_deleting' or 'error', the
manager will raise an exception and the status of group_snapshot will
be set to 'error' in the db. If snapshots_model_update is not returned
by the driver, the manager will set the status of every snapshot to
'error' in the except block.

If the driver raises an exception during the operation, it will be
caught by the try-except block in the manager and the statuses of
group_snapshot and all snapshots will be set to 'error'.

For a successful operation, the driver can either build the
model_update and snapshots_model_update and return them or
return None, None. The statuses of group_snapshot and all snapshots
will be set to 'deleted' after the manager deletes them from db.

Migrate CGs to Generic Volume Groups
------------------------------------

This section only affects drivers already supporting CGs by the
Newton release. Drivers planning to add CG support after Newton are
not affected.

A group type named default_cgsnapshot_type will be created by the
migration script. The following command needs to be run to migrate
migrate data and copy data from consistency groups to groups and
from cgsnapshots to group_snapshots. Migrated consistency groups
and cgsnapshots will be removed from the database::

    cinder-manage db online_data_migrations
    --max_count <max>
    --ignore_state

max_count is optional. Default is 50.
ignore_state is optional. Default is False.

After running the above migration command to migrate CGs to generic
volume groups, CG and group APIs work as follows:

* Create CG only creates in the groups table.

* Modify CG modifies in the CG table if the CG is in the
  CG table, otherwise it modifies in the groups table.

* Delete CG deletes from the CG or the groups table
  depending on where the CG is.

* List CG checks both CG and groups tables.

* List CG Snapshots checks both the CG and the groups
  tables.

* Show CG checks both tables.

* Show CG Snapshot checks both tables.

* Create CG Snapshot creates either in the CG or the groups
  table depending on where the CG is.

* Create CG from Source creates in either the CG or the
  groups table depending on the source.

* Create Volume adds the volume either to the CG or the
  group.

* default_cgsnapshot_type is reserved for migrating CGs.

* Group APIs will only write/read in/from the groups table.

* Group APIs will not work on groups with default_cgsnapshot_type.

* Groups with default_cgsnapshot_type can only be operated by
  CG APIs.

* After CG tables are removed, we will allow default_cgsnapshot_type
  to be used by group APIs.

References
----------
[1] Migration script
    https://review.openstack.org/#/c/350350/
[2] CG APIs changes for migrating CGs
    https://review.openstack.org/#/c/401839/
[3] Example adding CG capability to generic volume groups
    https://review.openstack.org/#/c/413927/
