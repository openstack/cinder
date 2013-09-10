# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
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


import os

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
    for key in kwargs:
        vol[key] = kwargs[key]
    return db.volume_create(ctxt, vol)


def create_snapshot(ctxt,
                    volume_id,
                    display_name='test_snapshot',
                    display_description='this is a test snapshot',
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
    return db.snapshot_create(ctxt, snap)
