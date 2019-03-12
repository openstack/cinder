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

from oslo_serialization import jsonutils

from cinder.tests.functional.api_sample_tests import test_volumes


class VolumeSnapshotsSampleJsonTest(test_volumes.VolumesSampleBase):
    sample_dir = "snapshots"

    def setUp(self):
        super(VolumeSnapshotsSampleJsonTest, self).setUp()
        res = self._create_volume()
        res = jsonutils.loads(res.content)['volume']
        self._poll_volume_while(res['id'], ['creating'])
        self.subs = {
            "volume_id": res['id']
        }
        self.response = self._create_snapshot(self.subs)

    def _create_snapshot(self, subs=None):
        response = self._do_post('snapshots',
                                 'snapshot-create-request',
                                 subs)
        return response

    def test_snapshot_list_detail(self):

        response = self._do_get('snapshots/detail')
        self._verify_response('snapshots-list-detailed-response',
                              {}, response, 200)

    def test_snapshot_create(self):

        self._verify_response('snapshot-create-response',
                              {}, self.response, 202)

    def test_snapshot_list(self):

        response = self._do_get('snapshots')
        self._verify_response('snapshots-list-response',
                              {}, response, 200)

    def test_snapshot_metadata_show(self):

        res = jsonutils.loads(self.response.content)['snapshot']
        response = self._do_get('snapshots/%s/metadata' % res['id'])
        self._verify_response('snapshot-metadata-show-response',
                              {}, response, 200)

    def test_snapshot_metadata_create(self):

        res = jsonutils.loads(self.response.content)['snapshot']
        response = self._do_post('snapshots/%s/metadata' % res['id'],
                                 'snapshot-metadata-create-request')
        self._verify_response('snapshot-metadata-create-response',
                              {}, response, 200)

    def test_snapshot_metadata_update(self):

        res = jsonutils.loads(self.response.content)['snapshot']
        response = self._do_put('snapshots/%s/metadata' % res['id'],
                                'snapshot-metadata-update-request')
        self._verify_response('snapshot-metadata-update-response',
                              {}, response, 200)

    def test_snapshot_show(self):

        res = jsonutils.loads(self.response.content)['snapshot']
        response = self._do_get('snapshots/%s' % res['id'])
        self._verify_response('snapshot-show-response',
                              {}, response, 200)

    def test_snapshot_update(self):

        res = jsonutils.loads(self.response.content)['snapshot']
        response = self._do_put('snapshots/%s' % res['id'],
                                'snapshot-update-request')
        self._verify_response('snapshot-update-response',
                              {}, response, 200)

    def test_snapshot_metadata_show_specific_key(self):

        res = jsonutils.loads(self.response.content)['snapshot']
        response = self._do_get('snapshots/%s/metadata/key' % res['id'])
        self._verify_response('snapshot-metadata-show-key-response',
                              {}, response, 200)

    def test_snapshot_metadata_update_specific_key(self):

        res = jsonutils.loads(self.response.content)['snapshot']
        response = self._do_put('snapshots/%s/metadata/key' % res['id'],
                                'snapshot-metadata-update-key-request')
        self._verify_response('snapshot-metadata-update-key-response',
                              {}, response, 200)
