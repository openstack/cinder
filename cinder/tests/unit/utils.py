#    Copyright 2011 OpenStack Foundation
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
#

import datetime
import socket
import sys
import uuid

from oslo_service import loopingcall
from oslo_utils import timeutils
import oslo_versionedobjects

from cinder import context
from cinder import db
from cinder import exception
from cinder import objects
from cinder.objects import fields
from cinder.tests.unit import fake_constants as fake


def get_test_admin_context():
    return context.get_admin_context()


def create_volume(ctxt,
                  host='test_host',
                  display_name='test_volume',
                  display_description='this is a test volume',
                  status='available',
                  migration_status=None,
                  size=1,
                  availability_zone='fake_az',
                  volume_type_id=None,
                  replication_status='disabled',
                  replication_extended_status=None,
                  replication_driver_data=None,
                  consistencygroup_id=None,
                  group_id=None,
                  previous_status=None,
                  testcase_instance=None,
                  **kwargs):
    """Create a volume object in the DB."""
    vol = {}
    vol['size'] = size
    vol['host'] = host
    vol['user_id'] = ctxt.user_id
    vol['project_id'] = ctxt.project_id
    vol['status'] = status
    if migration_status:
        vol['migration_status'] = migration_status
    vol['display_name'] = display_name
    vol['display_description'] = display_description
    vol['attach_status'] = 'detached'
    vol['availability_zone'] = availability_zone
    if consistencygroup_id:
        vol['consistencygroup_id'] = consistencygroup_id
    if group_id:
        vol['group_id'] = group_id
    if volume_type_id:
        vol['volume_type_id'] = volume_type_id
    for key in kwargs:
        vol[key] = kwargs[key]
    vol['replication_status'] = replication_status

    if replication_extended_status:
        vol['replication_extended_status'] = replication_extended_status
    if replication_driver_data:
        vol['replication_driver_data'] = replication_driver_data
    if previous_status:
        vol['previous_status'] = previous_status

    volume = objects.Volume(ctxt, **vol)
    volume.create()

    # If we get a TestCase instance we add cleanup
    if testcase_instance:
        testcase_instance.addCleanup(volume.destroy)
    return volume


def attach_volume(ctxt, volume_id, instance_uuid, attached_host,
                  mountpoint, mode='rw'):

    now = timeutils.utcnow()
    values = {}
    values['volume_id'] = volume_id
    values['attached_host'] = attached_host
    values['mountpoint'] = mountpoint
    values['attach_time'] = now

    attachment = db.volume_attach(ctxt, values)
    return db.volume_attached(ctxt, attachment['id'], instance_uuid,
                              attached_host, mountpoint, mode)


def create_snapshot(ctxt,
                    volume_id,
                    display_name='test_snapshot',
                    display_description='this is a test snapshot',
                    cgsnapshot_id = None,
                    status=fields.SnapshotStatus.CREATING,
                    testcase_instance=None,
                    **kwargs):
    vol = db.volume_get(ctxt, volume_id)
    snap = objects.Snapshot(ctxt)
    snap.volume_id = volume_id
    snap.user_id = ctxt.user_id or fake.USER_ID
    snap.project_id = ctxt.project_id or fake.PROJECT_ID
    snap.status = status
    snap.volume_size = vol['size']
    snap.display_name = display_name
    snap.display_description = display_description
    snap.cgsnapshot_id = cgsnapshot_id
    snap.create()
    # We do the update after creating the snapshot in case we want to set
    # deleted field
    snap.update(kwargs)
    snap.save()

    # If we get a TestCase instance we add cleanup
    if testcase_instance:
        testcase_instance.addCleanup(snap.destroy)
    return snap


def create_consistencygroup(ctxt,
                            host='test_host@fakedrv#fakepool',
                            name='test_cg',
                            description='this is a test cg',
                            status=fields.ConsistencyGroupStatus.AVAILABLE,
                            availability_zone='fake_az',
                            volume_type_id=None,
                            cgsnapshot_id=None,
                            source_cgid=None,
                            **kwargs):
    """Create a consistencygroup object in the DB."""

    cg = objects.ConsistencyGroup(ctxt)
    cg.host = host
    cg.user_id = ctxt.user_id or fake.USER_ID
    cg.project_id = ctxt.project_id or fake.PROJECT_ID
    cg.status = status
    cg.name = name
    cg.description = description
    cg.availability_zone = availability_zone

    if volume_type_id:
        cg.volume_type_id = volume_type_id
    cg.cgsnapshot_id = cgsnapshot_id
    cg.source_cgid = source_cgid
    new_id = kwargs.pop('id', None)
    cg.update(kwargs)
    cg.create()
    if new_id and new_id != cg.id:
        db.consistencygroup_update(ctxt, cg.id, {'id': new_id})
        cg = objects.ConsistencyGroup.get_by_id(ctxt, new_id)
    return cg


def create_group(ctxt,
                 host='test_host@fakedrv#fakepool',
                 name='test_group',
                 description='this is a test group',
                 status=fields.GroupStatus.AVAILABLE,
                 availability_zone='fake_az',
                 group_type_id=None,
                 volume_type_ids=None,
                 **kwargs):
    """Create a group object in the DB."""

    grp = objects.Group(ctxt)
    grp.host = host
    grp.user_id = ctxt.user_id or fake.USER_ID
    grp.project_id = ctxt.project_id or fake.PROJECT_ID
    grp.status = status
    grp.name = name
    grp.description = description
    grp.availability_zone = availability_zone
    if group_type_id:
        grp.group_type_id = group_type_id
    if volume_type_ids:
        grp.volume_type_ids = volume_type_ids
    new_id = kwargs.pop('id', None)
    grp.update(kwargs)
    grp.create()
    if new_id and new_id != grp.id:
        db.group_update(ctxt, grp.id, {'id': new_id})
        grp = objects.Group.get_by_id(ctxt, new_id)
    return grp


def create_cgsnapshot(ctxt,
                      consistencygroup_id,
                      name='test_cgsnapshot',
                      description='this is a test cgsnapshot',
                      status='creating',
                      recursive_create_if_needed=True,
                      return_vo=True,
                      **kwargs):
    """Create a cgsnapshot object in the DB."""
    values = {
        'user_id': ctxt.user_id or fake.USER_ID,
        'project_id': ctxt.project_id or fake.PROJECT_ID,
        'status': status,
        'name': name,
        'description': description,
        'consistencygroup_id': consistencygroup_id}
    values.update(kwargs)

    if recursive_create_if_needed and consistencygroup_id:
        create_cg = False
        try:
            objects.ConsistencyGroup.get_by_id(ctxt,
                                               consistencygroup_id)
            create_vol = not db.volume_get_all_by_group(
                ctxt, consistencygroup_id)
        except exception.ConsistencyGroupNotFound:
            create_cg = True
            create_vol = True
        if create_cg:
            create_consistencygroup(ctxt, id=consistencygroup_id)
        if create_vol:
            create_volume(ctxt, consistencygroup_id=consistencygroup_id)

    cgsnap = db.cgsnapshot_create(ctxt, values)

    if not return_vo:
        return cgsnap

    return objects.CGSnapshot.get_by_id(ctxt, cgsnap.id)


def create_group_snapshot(ctxt,
                          group_id,
                          group_type_id=None,
                          name='test_group_snapshot',
                          description='this is a test group snapshot',
                          status='creating',
                          recursive_create_if_needed=True,
                          return_vo=True,
                          **kwargs):
    """Create a group snapshot object in the DB."""
    values = {
        'user_id': ctxt.user_id or fake.USER_ID,
        'project_id': ctxt.project_id or fake.PROJECT_ID,
        'status': status,
        'name': name,
        'description': description,
        'group_id': group_id}
    values.update(kwargs)

    if recursive_create_if_needed and group_id:
        create_grp = False
        try:
            objects.Group.get_by_id(ctxt,
                                    group_id)
            create_vol = not db.volume_get_all_by_generic_group(
                ctxt, group_id)
        except exception.GroupNotFound:
            create_grp = True
            create_vol = True
        if create_grp:
            create_group(ctxt, id=group_id, group_type_id=group_type_id)
        if create_vol:
            create_volume(ctxt, group_id=group_id)

    if not return_vo:
        return db.group_snapshot_create(ctxt, values)
    else:
        group_snapshot = objects.GroupSnapshot(ctxt)
        new_id = values.pop('id', None)
        group_snapshot.update(values)
        group_snapshot.create()
        if new_id and new_id != group_snapshot.id:
            db.group_snapshot_update(ctxt, group_snapshot.id, {'id': new_id})
            group_snapshot = objects.GroupSnapshot.get_by_id(ctxt, new_id)
        return group_snapshot


def create_backup(ctxt,
                  volume_id=fake.VOLUME_ID,
                  display_name='test_backup',
                  display_description='This is a test backup',
                  status=fields.BackupStatus.CREATING,
                  parent_id=None,
                  temp_volume_id=None,
                  temp_snapshot_id=None,
                  snapshot_id=None,
                  data_timestamp=None,
                  **kwargs):
    """Create a backup object."""
    values = {
        'user_id': ctxt.user_id or fake.USER_ID,
        'project_id': ctxt.project_id or fake.PROJECT_ID,
        'volume_id': volume_id,
        'status': status,
        'display_name': display_name,
        'display_description': display_description,
        'container': 'fake',
        'availability_zone': 'fake',
        'service': 'fake',
        'size': 5 * 1024 * 1024,
        'object_count': 22,
        'host': socket.gethostname(),
        'parent_id': parent_id,
        'temp_volume_id': temp_volume_id,
        'temp_snapshot_id': temp_snapshot_id,
        'snapshot_id': snapshot_id,
        'data_timestamp': data_timestamp, }

    values.update(kwargs)
    backup = objects.Backup(ctxt, **values)
    backup.create()
    return backup


def create_message(ctxt,
                   project_id='fake_project',
                   request_id='test_backup',
                   resource_type='This is a test backup',
                   resource_uuid='3asf434-3s433df43-434adf3-343df443',
                   event_id=None,
                   message_level='Error'):
    """Create a message in the DB."""
    expires_at = (timeutils.utcnow() + datetime.timedelta(
                  seconds=30))
    message_record = {'project_id': project_id,
                      'request_id': request_id,
                      'resource_type': resource_type,
                      'resource_uuid': resource_uuid,
                      'event_id': event_id,
                      'message_level': message_level,
                      'expires_at': expires_at}
    return db.message_create(ctxt, message_record)


def create_volume_type(ctxt, testcase_instance=None, **kwargs):
    vol_type = db.volume_type_create(ctxt, kwargs)

    # If we get a TestCase instance we add cleanup
    if testcase_instance:
        testcase_instance.addCleanup(db.volume_type_destroy, ctxt, vol_type.id)

    return vol_type


def create_encryption(ctxt, vol_type_id, testcase_instance=None, **kwargs):
    encrypt = db.volume_type_encryption_create(ctxt, vol_type_id, kwargs)

    # If we get a TestCase instance we add cleanup
    if testcase_instance:
        testcase_instance.addCleanup(db.volume_type_encryption_delete, ctxt,
                                     vol_type_id)
    return encrypt


def create_qos(ctxt, testcase_instance=None, **kwargs):
    qos = db.qos_specs_create(ctxt, kwargs)
    if testcase_instance:
        testcase_instance.addCleanup(db.qos_specs_delete, ctxt, qos['id'])
    return qos


class ZeroIntervalLoopingCall(loopingcall.FixedIntervalLoopingCall):
    def start(self, interval, **kwargs):
        kwargs['initial_delay'] = 0
        return super(ZeroIntervalLoopingCall, self).start(0, **kwargs)


def replace_obj_loader(testcase, obj):
    def fake_obj_load_attr(self, name):
        # This will raise KeyError for non existing fields as expected
        field = self.fields[name]

        if field.default != oslo_versionedobjects.fields.UnspecifiedDefault:
            value = field.default
        elif field.nullable:
            value = None
        elif isinstance(field, oslo_versionedobjects.fields.StringField):
            value = ''
        elif isinstance(field, oslo_versionedobjects.fields.IntegerField):
            value = 1
        elif isinstance(field, oslo_versionedobjects.fields.UUIDField):
            value = uuid.uuid4()
        setattr(self, name, value)

    testcase.addCleanup(setattr, obj, 'obj_load_attr', obj.obj_load_attr)
    obj.obj_load_attr = fake_obj_load_attr


file_spec = None


def get_file_spec():
    """Return a Python 2 and 3 compatible version of a 'file' spec.

    This is to be used anywhere that you need to do something such as
    mock.MagicMock(spec=file) to mock out something with the file attributes.

    Due to the 'file' built-in method being removed in Python 3 we need to do
    some special handling for it.
    """
    global file_spec
    # set on first use
    if file_spec is None:
        if sys.version_info[0] == 3:
            import _io
            file_spec = list(set(dir(_io.TextIOWrapper)).union(
                set(dir(_io.BytesIO))))
        else:
            file_spec = file


def generate_timeout_series(timeout):
    """Generate a series of times that exceeds the given timeout.

    Yields a series of fake time.time() floating point numbers
    such that the difference between each pair in the series just
    exceeds the timeout value that is passed in.  Useful for
    mocking time.time() in methods that otherwise wait for timeout
    seconds.
    """
    iteration = 0
    while True:
        iteration += 1
        yield (iteration * timeout) + iteration
