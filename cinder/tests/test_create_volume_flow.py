# Copyright 2013 Canonical Ltd.
# All Rights Reserved.
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
""" Tests for create_volume TaskFlow """

import mock
import time

from cinder import context
from cinder import test
from cinder.volume.flows import create_volume


class fake_sheduler_rpc_api(object):
    def __init__(self, expected_spec, test_inst):
        self.expected_spec = expected_spec
        self.test_inst = test_inst

    def create_volume(self, ctxt, topic, volume_id, snapshot_id=None,
                      image_id=None, request_spec=None,
                      filter_properties=None):

        self.test_inst.assertEquals(self.expected_spec, request_spec)


class fake_volume_api(object):
    def __init__(self, expected_spec, test_inst):
        self.expected_spec = expected_spec
        self.test_inst = test_inst

    def create_volume(self, ctxt, volume, host,
                      request_spec, filter_properties,
                      allow_reschedule=True,
                      snapshot_id=None, image_id=None,
                      source_volid=None):

        self.test_inst.assertEquals(self.expected_spec, request_spec)
        self.test_inst.assertEquals(request_spec['source_volid'],
                                    source_volid)
        self.test_inst.assertEquals(request_spec['snapshot_id'],
                                    snapshot_id)
        self.test_inst.assertEquals(request_spec['image_id'],
                                    image_id)


class fake_db(object):

    def volume_get(self, *args, **kwargs):
        return {'host': 'barf'}

    def volume_update(self, *args, **kwargs):
        return {'host': 'farb'}

    def snapshot_get(self, *args, **kwargs):
        return {'volume_id': 1}


class CreateVolumeFlowTestCase(test.TestCase):

    def time_inc(self):
        self.counter += 1
        return self.counter

    def setUp(self):
        super(CreateVolumeFlowTestCase, self).setUp()
        self.ctxt = context.get_admin_context()
        self.counter = float(0)

        # Ensure that time.time() always returns more than the last time it was
        # called to avoid div by zero errors.
        self.counter = float(0)
        self.stubs.Set(time, 'time', self.time_inc)

    def test_cast_create_volume(self):

        props = {}
        spec = {'volume_id': None,
                'source_volid': None,
                'snapshot_id': None,
                'image_id': None}

        task = create_volume.VolumeCastTask(fake_sheduler_rpc_api(spec, self),
                                            fake_volume_api(spec, self),
                                            fake_db())

        task._cast_create_volume(self.ctxt, spec, props)

        spec = {'volume_id': 1,
                'source_volid': 2,
                'snapshot_id': 3,
                'image_id': 4}

        task = create_volume.VolumeCastTask(fake_sheduler_rpc_api(spec, self),
                                            fake_volume_api(spec, self),
                                            fake_db())

        task._cast_create_volume(self.ctxt, spec, props)

    def tearDown(self):
        self.stubs.UnsetAll()
        super(CreateVolumeFlowTestCase, self).tearDown()
