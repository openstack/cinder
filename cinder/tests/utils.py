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

from cinder import context
from cinder import db
from cinder.openstack.common import loopingcall

from oslo_utils import timeutils


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
                            host='test_host',
                            name='test_cg',
                            description='this is a test cg',
                            status='available',
                            availability_zone='fake_az',
                            volume_type_id=None,
                            cgsnapshot_id=None,
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


class ZeroIntervalLoopingCall(loopingcall.FixedIntervalLoopingCall):
    def start(self, interval, **kwargs):
        kwargs['initial_delay'] = 0
        return super(ZeroIntervalLoopingCall, self).start(0, **kwargs)
