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


class FakeVolumeAPI(object):
    def __init__(self, expected_spec, test_inst):
        self.expected_spec = expected_spec
        self.test_inst = test_inst

    def create_volume(self, ctxt, volume, host,
                      request_spec, filter_properties,
                      allow_reschedule=True,
                      snapshot_id=None, image_id=None,
                      source_volid=None,
                      source_replicaid=None):

        self.test_inst.assertEqual(self.expected_spec, request_spec)
        self.test_inst.assertEqual(request_spec['source_volid'], source_volid)
        self.test_inst.assertEqual(request_spec['snapshot_id'], snapshot_id)
        self.test_inst.assertEqual(request_spec['image_id'], image_id)
        self.test_inst.assertEqual(request_spec['source_replicaid'],
                                   source_replicaid)


class FakeSchedulerRpcAPI(object):
    def __init__(self, expected_spec, test_inst):
        self.expected_spec = expected_spec
        self.test_inst = test_inst

    def create_volume(self, ctxt, volume, snapshot_id=None, image_id=None,
                      request_spec=None, filter_properties=None):

        self.test_inst.assertEqual(self.expected_spec, request_spec)

    def manage_existing(self, context, volume, request_spec=None):
        self.test_inst.assertEqual(self.expected_spec, request_spec)


class FakeDb(object):

    def volume_get(self, *args, **kwargs):
        return {'host': 'barf'}

    def volume_update(self, *args, **kwargs):
        return {'host': 'farb'}

    def snapshot_get(self, *args, **kwargs):
        return {'volume_id': 1}

    def consistencygroup_get(self, *args, **kwargs):
        return {'consistencygroup_id': 1}
