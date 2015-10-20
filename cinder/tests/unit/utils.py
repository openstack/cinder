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

import socket
import sys
import uuid

from oslo_service import loopingcall
from oslo_utils import timeutils
import oslo_versionedobjects

from cinder import context
from cinder import db
from cinder import objects


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
                  previous_status=None,
                  **kwargs):
    """Create a volume object in the DB."""
    vol = {}
    vol['size'] = size
    vol['host'] = host
    vol['user_id'] = ctxt.user_id
    vol['project_id'] = ctxt.project_id
    vol['status'] = status
    vol['migration_status'] = migration_status
    vol['display_name'] = display_name
    vol['display_description'] = display_description
    vol['attach_status'] = 'detached'
    vol['availability_zone'] = availability_zone
    if consistencygroup_id:
        vol['consistencygroup_id'] = consistencygroup_id
    if volume_type_id:
        vol['volume_type_id'] = volume_type_id
    for key in kwargs:
        vol[key] = kwargs[key]
    vol['replication_status'] = replication_status
    vol['replication_extended_status'] = replication_extended_status
    vol['replication_driver_data'] = replication_driver_data
    vol['previous_status'] = previous_status

    return db.volume_create(ctxt, vol)


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
                    status='creating',
                    **kwargs):
    vol = db.volume_get(ctxt, volume_id)
    snap = objects.Snapshot(ctxt)
    snap.volume_id = volume_id
    snap.user_id = ctxt.user_id or 'fake_user_id'
    snap.project_id = ctxt.project_id or 'fake_project_id'
    snap.status = status
    snap.volume_size = vol['size']
    snap.display_name = display_name
    snap.display_description = display_description
    snap.cgsnapshot_id = cgsnapshot_id
    snap.create()
    return snap


def create_consistencygroup(ctxt,
                            host='test_host@fakedrv#fakepool',
                            name='test_cg',
                            description='this is a test cg',
                            status='available',
                            availability_zone='fake_az',
                            volume_type_id=None,
                            cgsnapshot_id=None,
                            source_cgid=None,
                            **kwargs):
    """Create a consistencygroup object in the DB."""

    cg = objects.ConsistencyGroup(ctxt)
    cg.host = host
    cg.user_id = ctxt.user_id or 'fake_user_id'
    cg.project_id = ctxt.project_id or 'fake_project_id'
    cg.status = status
    cg.name = name
    cg.description = description
    cg.availability_zone = availability_zone

    if volume_type_id:
        cg.volume_type_id = volume_type_id
    cg.cgsnapshot_id = cgsnapshot_id
    cg.source_cgid = source_cgid
    for key in kwargs:
        setattr(cg, key, kwargs[key])
    cg.create()
    return cg


def create_cgsnapshot(ctxt,
                      consistencygroup_id,
                      name='test_cgsnapshot',
                      description='this is a test cgsnapshot',
                      status='creating',
                      **kwargs):
    """Create a cgsnapshot object in the DB."""
    cgsnap = objects.CGSnapshot(ctxt)
    cgsnap.user_id = ctxt.user_id or 'fake_user_id'
    cgsnap.project_id = ctxt.project_id or 'fake_project_id'
    cgsnap.status = status
    cgsnap.name = name
    cgsnap.description = description
    cgsnap.consistencygroup_id = consistencygroup_id
    for key in kwargs:
        setattr(cgsnap, key, kwargs[key])
    cgsnap.create()
    return cgsnap


def create_backup(ctxt,
                  volume_id,
                  display_name='test_backup',
                  display_description='This is a test backup',
                  status='creating',
                  parent_id=None,
                  temp_volume_id=None,
                  temp_snapshot_id=None):
    backup = {}
    backup['volume_id'] = volume_id
    backup['user_id'] = ctxt.user_id
    backup['project_id'] = ctxt.project_id
    backup['host'] = socket.gethostname()
    backup['availability_zone'] = '1'
    backup['display_name'] = display_name
    backup['display_description'] = display_description
    backup['container'] = 'fake'
    backup['status'] = status
    backup['fail_reason'] = ''
    backup['service'] = 'fake'
    backup['parent_id'] = parent_id
    backup['size'] = 5 * 1024 * 1024
    backup['object_count'] = 22
    backup['temp_volume_id'] = temp_volume_id
    backup['temp_snapshot_id'] = temp_snapshot_id
    return db.backup_create(ctxt, backup)


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
