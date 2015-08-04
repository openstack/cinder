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

from oslo_service import loopingcall
from oslo_utils import timeutils

from cinder import context
from cinder import db


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
                    status='creating'):
    vol = db.volume_get(ctxt, volume_id)
    snap = {}
    snap['volume_id'] = volume_id
    snap['user_id'] = ctxt.user_id
    snap['project_id'] = ctxt.project_id
    snap['status'] = status
    snap['volume_size'] = vol['size']
    snap['display_name'] = display_name
    snap['display_description'] = display_description
    snap['cgsnapshot_id'] = cgsnapshot_id
    return db.snapshot_create(ctxt, snap)


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
    cg = {}
    cg['host'] = host
    cg['user_id'] = ctxt.user_id
    cg['project_id'] = ctxt.project_id
    cg['status'] = status
    cg['name'] = name
    cg['description'] = description
    cg['availability_zone'] = availability_zone
    if volume_type_id:
        cg['volume_type_id'] = volume_type_id
    cg['cgsnapshot_id'] = cgsnapshot_id
    cg['source_cgid'] = source_cgid
    for key in kwargs:
        cg[key] = kwargs[key]
    return db.consistencygroup_create(ctxt, cg)


def create_cgsnapshot(ctxt,
                      name='test_cgsnap',
                      description='this is a test cgsnap',
                      status='available',
                      consistencygroup_id=None,
                      **kwargs):
    """Create a cgsnapshot object in the DB."""
    cgsnap = {}
    cgsnap['user_id'] = ctxt.user_id
    cgsnap['project_id'] = ctxt.project_id
    cgsnap['status'] = status
    cgsnap['name'] = name
    cgsnap['description'] = description
    cgsnap['consistencygroup_id'] = consistencygroup_id
    for key in kwargs:
        cgsnap[key] = kwargs[key]
    return db.cgsnapshot_create(ctxt, cgsnap)


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
