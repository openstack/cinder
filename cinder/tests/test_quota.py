# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

from cinder import context
from cinder import db
from cinder import exception
from cinder import flags
from cinder import quota
from cinder.openstack.common import rpc
from cinder import test
from cinder import volume
from cinder.scheduler import driver as scheduler_driver


FLAGS = flags.FLAGS


class GetQuotaTestCase(test.TestCase):
    def setUp(self):
        super(GetQuotaTestCase, self).setUp()
        self.flags(quota_instances=10,
                   quota_cores=20,
                   quota_ram=50 * 1024,
                   quota_volumes=10,
                   quota_gigabytes=1000,
                   quota_floating_ips=10,
                   quota_security_groups=10,
                   quota_security_group_rules=20,
                   quota_metadata_items=128,
                   quota_injected_files=5,
                   quota_injected_file_content_bytes=10 * 1024)
        self.context = context.RequestContext('admin', 'admin', is_admin=True)

    def _stub_class(self):
        def fake_quota_class_get_all_by_name(context, quota_class):
            result = dict(class_name=quota_class)
            if quota_class == 'test_class':
                result.update(
                    instances=5,
                    cores=10,
                    ram=25 * 1024,
                    volumes=5,
                    gigabytes=500,
                    floating_ips=5,
                    quota_security_groups=10,
                    quota_security_group_rules=20,
                    metadata_items=64,
                    injected_files=2,
                    injected_file_content_bytes=5 * 1024,
                    invalid_quota=100,
                    )
            return result

        self.stubs.Set(db, 'quota_class_get_all_by_name',
                       fake_quota_class_get_all_by_name)

    def _stub_project(self, override=False):
        def fake_quota_get_all_by_project(context, project_id):
            result = dict(project_id=project_id)
            if override:
                result.update(
                    instances=2,
                    cores=5,
                    ram=12 * 1024,
                    volumes=2,
                    gigabytes=250,
                    floating_ips=2,
                    security_groups=5,
                    security_group_rules=10,
                    metadata_items=32,
                    injected_files=1,
                    injected_file_content_bytes=2 * 1024,
                    invalid_quota=50,
                    )
            return result

        self.stubs.Set(db, 'quota_get_all_by_project',
                       fake_quota_get_all_by_project)

    def test_default_quotas(self):
        result = quota._get_default_quotas()
        self.assertEqual(result, dict(
                instances=10,
                cores=20,
                ram=50 * 1024,
                volumes=10,
                gigabytes=1000,
                floating_ips=10,
                security_groups=10,
                security_group_rules=20,
                metadata_items=128,
                injected_files=5,
                injected_file_content_bytes=10 * 1024,
                ))

    def test_default_quotas_unlimited(self):
        self.flags(quota_instances=-1,
                   quota_cores=-1,
                   quota_ram=-1,
                   quota_volumes=-1,
                   quota_gigabytes=-1,
                   quota_floating_ips=-1,
                   quota_security_groups=-1,
                   quota_security_group_rules=-1,
                   quota_metadata_items=-1,
                   quota_injected_files=-1,
                   quota_injected_file_content_bytes=-1)
        result = quota._get_default_quotas()
        self.assertEqual(result, dict(
                instances=-1,
                cores=-1,
                ram=-1,
                volumes=-1,
                gigabytes=-1,
                floating_ips=-1,
                security_groups=-1,
                security_group_rules=-1,
                metadata_items=-1,
                injected_files=-1,
                injected_file_content_bytes=-1,
                ))

    def test_class_quotas_noclass(self):
        self._stub_class()
        result = quota.get_class_quotas(self.context, 'noclass')
        self.assertEqual(result, dict(
                instances=10,
                cores=20,
                ram=50 * 1024,
                volumes=10,
                gigabytes=1000,
                floating_ips=10,
                security_groups=10,
                security_group_rules=20,
                metadata_items=128,
                injected_files=5,
                injected_file_content_bytes=10 * 1024,
                ))

    def test_class_quotas(self):
        self._stub_class()
        result = quota.get_class_quotas(self.context, 'test_class')
        self.assertEqual(result, dict(
                instances=5,
                cores=10,
                ram=25 * 1024,
                volumes=5,
                gigabytes=500,
                floating_ips=5,
                security_groups=10,
                security_group_rules=20,
                metadata_items=64,
                injected_files=2,
                injected_file_content_bytes=5 * 1024,
                ))

    def test_project_quotas_defaults_noclass(self):
        self._stub_class()
        self._stub_project()
        result = quota.get_project_quotas(self.context, 'admin')
        self.assertEqual(result, dict(
                instances=10,
                cores=20,
                ram=50 * 1024,
                volumes=10,
                gigabytes=1000,
                floating_ips=10,
                security_groups=10,
                security_group_rules=20,
                metadata_items=128,
                injected_files=5,
                injected_file_content_bytes=10 * 1024,
                ))

    def test_project_quotas_overrides_noclass(self):
        self._stub_class()
        self._stub_project(True)
        result = quota.get_project_quotas(self.context, 'admin')
        self.assertEqual(result, dict(
                instances=2,
                cores=5,
                ram=12 * 1024,
                volumes=2,
                gigabytes=250,
                floating_ips=2,
                security_groups=5,
                security_group_rules=10,
                metadata_items=32,
                injected_files=1,
                injected_file_content_bytes=2 * 1024,
                ))

    def test_project_quotas_defaults_withclass(self):
        self._stub_class()
        self._stub_project()
        self.context.quota_class = 'test_class'
        result = quota.get_project_quotas(self.context, 'admin')
        self.assertEqual(result, dict(
                instances=5,
                cores=10,
                ram=25 * 1024,
                volumes=5,
                gigabytes=500,
                floating_ips=5,
                security_groups=10,
                security_group_rules=20,
                metadata_items=64,
                injected_files=2,
                injected_file_content_bytes=5 * 1024,
                ))

    def test_project_quotas_overrides_withclass(self):
        self._stub_class()
        self._stub_project(True)
        self.context.quota_class = 'test_class'
        result = quota.get_project_quotas(self.context, 'admin')
        self.assertEqual(result, dict(
                instances=2,
                cores=5,
                ram=12 * 1024,
                volumes=2,
                gigabytes=250,
                floating_ips=2,
                security_groups=5,
                security_group_rules=10,
                metadata_items=32,
                injected_files=1,
                injected_file_content_bytes=2 * 1024,
                ))


class QuotaTestCase(test.TestCase):

    class StubImageService(object):

        def show(self, *args, **kwargs):
            return {"properties": {}}

    def setUp(self):
        super(QuotaTestCase, self).setUp()
        self.flags(quota_volumes=2,
                   quota_gigabytes=20)
        self.user_id = 'admin'
        self.project_id = 'admin'
        self.context = context.RequestContext(self.user_id,
                                              self.project_id,
                                              is_admin=True)
        orig_rpc_call = rpc.call

        def rpc_call_wrapper(context, topic, msg, timeout=None):
            return orig_rpc_call(context, topic, msg)

        self.stubs.Set(rpc, 'call', rpc_call_wrapper)

    def _create_volume(self, size=10):
        """Create a test volume"""
        vol = {}
        vol['user_id'] = self.user_id
        vol['project_id'] = self.project_id
        vol['size'] = size
        return db.volume_create(self.context, vol)['id']

    def test_unlimited_volumes(self):
        self.flags(quota_volumes=10, quota_gigabytes=-1)
        volumes = quota.allowed_volumes(self.context, 100, 1)
        self.assertEqual(volumes, 10)
        db.quota_create(self.context, self.project_id, 'volumes', -1)
        volumes = quota.allowed_volumes(self.context, 100, 1)
        self.assertEqual(volumes, 100)
        volumes = quota.allowed_volumes(self.context, 101, 1)
        self.assertEqual(volumes, 101)

    def test_too_many_volumes(self):
        volume_ids = []
        for i in range(FLAGS.quota_volumes):
            volume_id = self._create_volume()
            volume_ids.append(volume_id)
        self.assertRaises(exception.QuotaError,
                          volume.API().create,
                          self.context, 10, '', '', None)
        for volume_id in volume_ids:
            db.volume_destroy(self.context, volume_id)

    def test_too_many_gigabytes(self):
        volume_ids = []
        volume_id = self._create_volume(size=20)
        volume_ids.append(volume_id)
        self.assertRaises(exception.QuotaError,
                          volume.API().create,
                          self.context, 10, '', '', None)
        for volume_id in volume_ids:
            db.volume_destroy(self.context, volume_id)
