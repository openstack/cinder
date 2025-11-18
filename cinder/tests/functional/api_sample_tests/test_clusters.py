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

from cinder.api import microversions as mv
from cinder.tests.functional import api_samples_test_base as test_base
from cinder.tests.unit.api.v3 import test_cluster


class ClustersSampleJsonTest(test_base.ApiSampleTestBase):
    sample_dir = "clusters"

    def setUp(self):
        super().setUp()
        self.stub_out(
            'cinder.db.sqlalchemy.api.cluster_get_all',
            test_cluster.fake_db_api_cluster_get_all)
        self.stub_out(
            'cinder.db.sqlalchemy.api.cluster_get',
            test_cluster.fake_db_api_cluster_get)
        self.stub_out(
            'cinder.db.sqlalchemy.api.cluster_update',
            test_cluster.fake_db_api_cluster_update)
        self.subs = {}

    @test_base.VolumesSampleBase.override_mv(mv.CLUSTER_SUPPORT)
    def test_cluster_list(self):
        response = self._do_get('clusters')
        self._verify_response(
            'clusters-list-response', {}, response, 200)

    @test_base.VolumesSampleBase.override_mv(mv.CLUSTER_SUPPORT)
    def test_cluster_enable(self):
        response = self._do_put(
            'clusters/enable', 'cluster-enable-request')
        self._verify_response(
            'cluster-enable-response', {}, response, 200)

    @test_base.VolumesSampleBase.override_mv(mv.CLUSTER_SUPPORT)
    def test_cluster_disable(self):
        response = self._do_put(
            'clusters/disable', 'cluster-disable-request')
        self._verify_response(
            'cluster-disable-response', {}, response, 200)

    @test_base.VolumesSampleBase.override_mv(mv.CLUSTER_SUPPORT)
    def test_cluster_show(self):
        response = self._do_get('clusters/cluster_name?binary=cinder-volume')
        self._verify_response(
            'cluster-show-response', {}, response, 200)

    @test_base.VolumesSampleBase.override_mv(mv.CLUSTER_SUPPORT)
    def test_cluster_list_detail(self):
        response = self._do_get('clusters/detail')
        self._verify_response(
            'clusters-list-detailed-response', {}, response, 200)
