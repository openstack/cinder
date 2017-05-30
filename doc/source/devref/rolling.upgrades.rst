..
      Copyright (c) 2016 Intel Corporation
      All Rights Reserved.

      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

Upgrades
========

Starting from Mitaka release Cinder gained the ability to be upgraded without
introducing downtime of control plane services. Operator can simply upgrade
Cinder services instances one-by-one. To achieve that, developers need to make
sure that any introduced change doesn't break older services running in the
same Cinder deployment.

In general there is a requirement that release N will keep backward
compatibility with release N-1 and in a deployment N's and N-1's services can
safely coexist. This means that when performing a live upgrade you cannot skip
any release (e.g. you cannot upgrade N to N+2 without upgrading it to N+1
first). Further in the document N will denote the current release, N-1 a
previous one, N+1 the next one, etc.

Having in mind that we only support compatibility with N-1, most of the
compatibility code written in N needs to exist just for one release and can be
removed in the beginning of N+1. A good practice here is to mark them with
:code:`TODO` or :code:`FIXME` comments to make them easy to find in the future.

Please note that proper upgrades solution should support both
release-to-release upgrades as well as upgrades of deployments following the
Cinder master more closely. We cannot just merge patches implementing
compatibility at the end of the release - we should keep things compatible
through the whole release.

To achieve compatibility, discipline is required from the developers. There are
several planes on which incompatibility may occur:

* **REST API changes** - these are prohibited by definition and this document
  will not describe the subject. For further information one may use `API
  Working Group guidelines
  <https://specs.openstack.org/openstack/api-wg/guidelines/evaluating_api_changes.html>`_
  for reference.

* **Database schema migrations** - e.g. if N-1 was relying on some column in
  the DB being present, N's migrations cannot remove it. N+1's however can
  (assuming N has no notion of the column).

* **Database data migrations** - if a migration requires big amount of data to
  be transferred between columns or tables or converted, it will most likely
  lock the tables. This may cause services to be unresponsive, causing the
  downtime.

* **RPC API changes** - adding or removing RPC method parameter, or the method
  itself, may lead to incompatibilities.

* **RPC payload changes** - adding, renaming or removing a field from the dict
  passed over RPC may lead to incompatibilities.

Next sections of this document will focus on explaining last four points and
provide means to tackle required changes in these matters while maintaining
backward compatibility.


Database schema and data migrations
-----------------------------------

In general incompatible database schema migrations can be tracked to ALTER and
DROP SQL commands instruction issued either against a column or table. This is
why a unit test that blocks such migrations was introduced. We should try to
keep our DB modifications additive. Moreover we should aim not to introduce
migrations that cause the database tables to lock for a long period. Long lock
on whole table can block other queries and may make real requests to fail.

Adding a column
...............

This is the simplest case - we don't have any requirements when adding a new
column apart from the fact that it should be added as the last one in the
table. If that's covered, the DB engine will make sure the migration won't be
disruptive.

Dropping a column not referenced in SQLAlchemy code
...................................................

When we want to remove a column that wasn't present in any SQLAlchemy model or
it was in the model, but model was not referenced in any SQLAlchemy API
function (this basically means that N-1 wasn't depending on the presence of
that column in the DB), then the situation is simple. We should be able to
safely drop the column in N release.

Removal of unnecessary column
.............................

When we want to remove a used column without migrating any data out of it (for
example because what's kept in the column is obsolete), then we just need to
remove it from the SQLAlchemy model and API in N release. In N+1 or as a
post-upgrade migration in N we can merge a migration issuing DROP for this
column (we cannot do that earlier because N-1 will depend on the presence of
that column).

ALTER on a column
.................

A rule of thumb to judge which ALTER or DROP migrations should be allowed is to
look in the `MySQL documentation
<https://dev.mysql.com/doc/refman/5.7/en/innodb-create-index-overview.html#innodb-online-ddl-summary-grid>`_.
If operation has "yes" in all 4 columns besides "Copies Table?", then it
*probably* can be allowed. If operation doesn't allow concurrent DML it means
that table row modifications or additions will be blocked during the migration.
This sometimes isn't a problem - for example it's not the end of the world if a
service won't be able to report it's status one or two times (and
:code:`services` table is normally small). Please note that even if this does
apply to "rename a column" operation, we cannot simply do such ALTER, as N-1
will depend on the older name.

If an operation on column or table cannot be allowed, then it is required to
create a new column with desired properties and start moving the data (in a
live manner). In worst case old column can be removed in N+2. Whole procedure
is described in more details below.

In aforementioned case we need to make more complicated steps stretching through
3 releases - always keeping the backwards compatibility. In short when we want
to start to move data inside the DB, then in N we should:

* Add a new column for the data.
* Write data in both places (N-1 needs to read it).
* Read data from the old place (N-1 writes there).
* Prepare online data migration cinder-manage command to be run before
  upgrading to N+1 (because N+1 will read from new place, so we need to make
  sure all the records have new place populated).

In N+1 we should:

* Write data to both places (N reads from old one).
* Read data from the new place (N saves there).

In N+2

* Remove old place from SQLAlchemy.
* Read and write only to the new place.
* Remove the column as the post-upgrade migration (or as first migration in
  N+3).

Please note that this is the most complicated case. If data in the column
cannot actually change (for example :code:`host` in :code:`services` table), in
N we can read from new place and fallback to the old place if data is missing.
This way we can skip one release from the process.

Of course real-world examples may be different. E.g. sometimes it may be
required to write some more compatibility code in the oslo.versionedobjects
layer to compensate for different versions of objects passed over RPC. This is
explained more in `RPC payload changes (oslo.versionedobjects)`_ section.

More details about that can be found in the `online-schema-upgrades spec
<http://specs.openstack.org/openstack/cinder-specs/specs/mitaka/online-schema-upgrades.html>`_.


RPC API changes
---------------

It can obviously break service communication if RPC interface changes. In
particular this applies to changes of the RPC method definitions. To avoid that
we assume N's RPC API compatibility with N-1 version (both ways -
:code:`rpcapi` module should be able to downgrade the message if needed and
:code:`manager` module should be able to tolerate receiving messages in older
version.

Below is an example RPC compatibility shim from Mitaka's
:code:`cinder.volume.manager`. This code allows us to tolerate older versions
of the messages::

    def create_volume(self, context, volume_id, request_spec=None,
                      filter_properties=None, allow_reschedule=True,
                      volume=None):

        """Creates the volume."""
        # FIXME(thangp): Remove this in v2.0 of RPC API.
        if volume is None:
            # For older clients, mimic the old behavior and look up the volume
            # by its volume_id.
            volume = objects.Volume.get_by_id(context, volume_id)

And here's a contrary shim in cinder.volume.rpcapi (RPC client) that downgrades
the message to make sure it will be understood by older instances of the
service::

    def create_volume(self, ctxt, volume, host, request_spec,
                      filter_properties, allow_reschedule=True):
        request_spec_p = jsonutils.to_primitive(request_spec)
        msg_args = {'volume_id': volume.id, 'request_spec': request_spec_p,
                    'filter_properties': filter_properties,
                    'allow_reschedule': allow_reschedule}
        if self.client.can_send_version('1.32'):
            version = '1.32'
            msg_args['volume'] = volume
        else:
            version = '1.24'

        new_host = utils.extract_host(host)
        cctxt = self.client.prepare(server=new_host, version=version)
        request_spec_p = jsonutils.to_primitive(request_spec)
        cctxt.cast(ctxt, 'create_volume', **msg_args)

As can be seen there's this magic :code:`self.client.can_send_version()` method
which detects if we're running in a version-heterogeneous environment and need
to downgrade the message. Detection is based on dynamic RPC version pinning. In
general all the services (managers) report supported RPC API version. RPC API
client gets all the versions from the DB, chooses the lowest one and starts to
downgrade messages to it.

To limit impact on the DB the pinned version of certain RPC API is cached.
After all the services in the deployment are updated, operator should restart
all the services or send them a SIGHUP signal to force reload of version pins.

As we need to support only N RPC API in N+1 release, we should be able to drop
all the compatibility shims in N+1. To be technically correct when doing so we
should also bump the major RPC API version. We do not need to do that in every
release (it may happen that through the release nothing will change in RPC API
or cost of technical debt of compatibility code is lower than the cost of
complicated procedure of increasing major version of RPC APIs).

The process of increasing the major version is explained in details in `Nova's
documentation <https://wiki.openstack.org/wiki/RpcMajorVersionUpdates>`_.
Please note that in case of Cinder we're accessing the DB from all of the
services, so we should follow the more complicated "Mixed version environments"
process for every of our services.

In case of removing whole RPC method we need to leave it there in N's manager
and can remove it in N+1 (because N-1 will be talking with N). When adding a
new one we need to make sure that when the RPC client is pinned to a too low
version any attempt to send new message should fail (because client will not
know if manager receiving the message will understand it) or ensure the manager
will get updated before clients by stating the recommended order of upgrades
for that release.

RPC payload changes (oslo.versionedobjects)
-------------------------------------------

`oslo.versionedobjects
<http://docs.openstack.org/developer/oslo.versionedobjects>`_ is a library that
helps us to maintain compatibility of the payload sent over RPC. As during the
process of upgrades it is possible that a newer version of the service will
send an object to an older one, it may happen that newer object is incompatible
with older service.

Version of an object should be bumped every time we make a change that will
result in an incompatible change of the serialized object.  Tests will inform
you when you need to bump the version of a versioned object, but rule of thumb
is that we should never bump the version when we modify/adding/removing a
method to the versioned object (unlike Nova we don't use remotable methods),
and should always bump it when we modify the fields dictionary.

There are exceptions to this rule, for example when we change a
``fields.StringField`` by a custom ``fields.BaseEnumField``.  The reason why a
version bump is not required in this case it's because the actual data doesn't
change, we are just removing magic string by an enumerate, but the strings used
are exactly the same.

As mentioned before, you don't have to know all the rules, as we have a test
that calculates the hash of all objects taking all these rules into
consideration and will tell you exactly when you need to bump the version of a
versioned object.

You can run this test with
``tox -epy35 -- --path cinder/tests/unit/objects/test_objects.py``.  But you
may need to run it multiple times until it passes since it may not detect all
required bumps at once.

Then you'll see which versioned object requires a bump and you need to bump
that version and update the object_data dictionary in the test file to reflect
the new version as well as the new hash.

There is a very common false positive on the version bump test, and that is
when we have modified a versioned object that is being used by other objects
using the ``fields.ObjectField`` class.  Due to the backporting mechanism
implemented in Cinder we don't require bumping the version for these cases and
we'll just need to update the hash used in the test.

For example if we were to add a new field to the Volume object and then run the
test we may think that we need to bump Volume, Snapshot, Backup, RequestSpec,
and VolumeAttachment objects, but we really only need to bump the version of
the Volume object and update the hash for all the other objects.

Imagine that we (finally!) decide that :code:`request_spec` sent in
:code:`create_volume` RPC cast is duplicating data and we want to start to
remove redundant occurrences.  When running in version-mixed environment older
services will still expect this redundant data. We need a way to somehow
downgrade the :code:`request_spec` before sending it over RPC. And this is were
o.vo come in handy. o.vo provide us the infrastructure to keep the changes in
object versioned and to be able to downgrade them to a particular version.

Let's take a step back - similarly to the RPC API situation we need a way to
tell if we need to send a backward-compatible version of the message. In this
case we need to know to what version to downgrade the object. We're using a
similar solution to the one used for RPC API for that. A problem here is that
we need a single identifier (that we will be reported to :code:`services` DB
table) to denote whole set of versions of all the objects. To do that we've
introduced a concept of :code:`CinderObjectVersionHistory` object, where we
keep sets of individual object versions aggregated into a single version
string. When making an incompatible change in a single object you need to bump
its version (we have a unit test enforcing that) *and* add a new version to
:code:`cinder.objects.base.CinderObjectVersionsHistory` (there's a unit test as
well). Example code doing that is below::

    OBJ_VERSIONS.add('1.1', {'Service': '1.2', 'ServiceList': '1.1'})

This line adds a new 1.1 aggregated object version that is different from 1.0
by two objects - :code:`Service` in 1.2 and :code:`ServiceList` in 1.1. This
means that the commit which added this line bumped versions of these two
objects.

Now if we know that a service we're talking to is running 1.1 aggregated
version - we need to downgrade :code:`Service` and :code:`ServiceList` to 1.2
and 1.1 respectively before sending. Please note that of course other objects
are included in the 1.1 aggregated version, but you just need to specify what
changed (all the other versions of individual objects will be taken from the
last version - 1.0 in this case).

Getting back to :code:`request_spec` example. So let's assume we want to remove
:code:`volume_properties` from there (most of data in there is already
somewhere else inside the :code:`request_spec` object). We've made a change in
the object fields, we've bumped it's version (from 1.0 to 1.1), we've updated
hash in the :code:`cinder.tests.unit.test_objects` to synchronize it with the
current state of the object, making the unit test pass and we've added a new
aggregated object history version in :code:`cinder.objects.base`.

What else is required? We need to provide code that actually downgrades
RequestSpec object from 1.1 to 1.0 - to be used when sending the object to
older services. This is done by implementing :code:`obj_make_compatible` method
in the object::

    from oslo_utils import versionutils

    def obj_make_compatible(self, primitive, target_version):
        super(RequestSpec, self).obj_make_compatible(primitive, target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 1) and not 'volume_properties' in primitive:
            volume_properties = {}
            # TODO: Aggregate all the required information from primitive.
            primitive['volume_properties'] = volume_properties

Please note that primitive is a dictionary representation of the object and not
an object itself. This is because o.vo are of course sent over RPC as dicts.

With these pieces in place Cinder will take care of sending
:code:`request_spec` with :code:`volume_properties` when running in mixed
environment and without when all services are upgraded and will understand
:code:`request_spec` without :code:`volume_properties` element.

Note that o.vo layer is able to recursively downgrade all of its fields, so
when `request_spec` will be used as a field in other object, it will be
correctly downgraded.

A more common case where we need backporting code is when we add new fields.
In such case the backporting consist on removing the newly added fields.  For
example if we add 3 new fields to the Group object in version 1.1, then we need
to remove them if backporting to earlier versions::

    from oslo_utils import versionutils

    def obj_make_compatible(self, primitive, target_version):
        super(Group, self).obj_make_compatible(primitive, target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 1):
            for key in ('group_snapshot_id', 'source_group_id',
                        'group_snapshots'):
                primitive.pop(key, None)

As time goes on we will be adding more and more new fields to our objects, so
we may end up with a long series of if and for statements like in the Volume
object::

    from oslo_utils import versionutils

    def obj_make_compatible(self, primitive, target_version):
        super(Volume, self).obj_make_compatible(primitive, target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 4):
            for key in ('cluster', 'cluster_name'):
                primitive.pop(key, None)
        if target_version < (1, 5):
            for key in ('group', 'group_id'):
                primitive.pop(key, None)

So a different pattern would be preferable as it will make the backporting
easier for future additions::

    from oslo_utils import versionutils

    def obj_make_compatible(self, primitive, target_version):
        added_fields = (((1, 4), ('cluster', 'cluster_name')),
                        ((1, 5), ('group', 'group_id')))
        super(Volume, self).obj_make_compatible(primitive, target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        for version, remove_fields in added_fields:
            if target_version < version:
                for obj_field in remove_fields:
                    primitive.pop(obj_field, None)
