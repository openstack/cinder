# Copyright (c) 2016 EMC Corporation, Inc.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import taskflow.engines
from taskflow.patterns import linear_flow
from taskflow.types import failure

from cinder.tests.unit.volume.drivers.dell_emc.vnx import fake_exception \
    as vnx_ex
from cinder.tests.unit.volume.drivers.dell_emc.vnx import res_mock
from cinder.tests.unit.volume.drivers.dell_emc.vnx import test_base
import cinder.volume.drivers.dell_emc.vnx.taskflows as vnx_taskflow


class TestTaskflow(test_base.TestCase):
    def setUp(self):
        super(TestTaskflow, self).setUp()
        self.work_flow = linear_flow.Flow('test_task')

    @res_mock.patch_client
    def test_copy_snapshot_task(self, client, mocked):
        store_spec = {'client': client,
                      'snap_name': 'original_name',
                      'new_snap_name': 'new_name'
                      }
        self.work_flow.add(vnx_taskflow.CopySnapshotTask())
        engine = taskflow.engines.load(self.work_flow,
                                       store=store_spec)
        engine.run()

    @res_mock.patch_client
    def test_copy_snapshot_task_revert(self, client, mocked):
        store_spec = {'client': client,
                      'snap_name': 'original_name',
                      'new_snap_name': 'new_name'
                      }
        self.work_flow.add(vnx_taskflow.CopySnapshotTask())
        engine = taskflow.engines.load(self.work_flow,
                                       store=store_spec)
        self.assertRaises(vnx_ex.VNXSnapError,
                          engine.run)

    @res_mock.patch_client
    def test_create_smp_task(self, client, mocked):
        store_spec = {
            'client': client,
            'smp_name': 'mount_point_name',
            'base_lun_name': 'base_name'
        }
        self.work_flow.add(vnx_taskflow.CreateSMPTask())
        engine = taskflow.engines.load(self.work_flow,
                                       store=store_spec)
        engine.run()
        smp_id = engine.storage.fetch('smp_id')
        self.assertEqual(15, smp_id)

    @res_mock.patch_client
    def test_create_smp_task_revert(self, client, mocked):
        store_spec = {
            'client': client,
            'smp_name': 'mount_point_name',
            'base_lun_name': 'base_name'
        }
        self.work_flow.add(vnx_taskflow.CreateSMPTask())
        engine = taskflow.engines.load(self.work_flow,
                                       store=store_spec)
        self.assertRaises(vnx_ex.VNXCreateLunError,
                          engine.run)
        smp_id = engine.storage.fetch('smp_id')
        self.assertIsInstance(smp_id, failure.Failure)

    @res_mock.patch_client
    def test_attach_snap_task(self, client, mocked):
        store_spec = {
            'client': client,
            'smp_name': 'mount_point_name',
            'snap_name': 'snap_name'
        }
        self.work_flow.add(vnx_taskflow.AttachSnapTask())
        engine = taskflow.engines.load(self.work_flow,
                                       store=store_spec)
        engine.run()

    @res_mock.patch_client
    def test_attach_snap_task_revert(self, client, mocked):
        store_spec = {
            'client': client,
            'smp_name': 'mount_point_name',
            'snap_name': 'snap_name'
        }
        self.work_flow.add(vnx_taskflow.AttachSnapTask())
        engine = taskflow.engines.load(self.work_flow,
                                       store=store_spec)
        self.assertRaises(vnx_ex.VNXAttachSnapError,
                          engine.run)

    @res_mock.patch_client
    def test_create_snapshot_task(self, client, mocked):
        store_spec = {
            'client': client,
            'lun_id': 12,
            'snap_name': 'snap_name'
        }
        self.work_flow.add(vnx_taskflow.CreateSnapshotTask())
        engine = taskflow.engines.load(self.work_flow,
                                       store=store_spec)
        engine.run()

    @res_mock.patch_client
    def test_create_snapshot_task_revert(self, client, mocked):
        store_spec = {
            'client': client,
            'lun_id': 13,
            'snap_name': 'snap_name'
        }
        self.work_flow.add(vnx_taskflow.CreateSnapshotTask())
        engine = taskflow.engines.load(self.work_flow,
                                       store=store_spec)
        self.assertRaises(vnx_ex.VNXCreateSnapError,
                          engine.run)

    @res_mock.patch_client
    def test_allow_read_write_task(self, client, mocked):
        store_spec = {
            'client': client,
            'snap_name': 'snap_name'
        }
        self.work_flow.add(vnx_taskflow.ModifySnapshotTask())
        engine = taskflow.engines.load(self.work_flow,
                                       store=store_spec)
        engine.run()

    @res_mock.patch_client
    def test_allow_read_write_task_revert(self, client, mocked):
        store_spec = {
            'client': client,
            'snap_name': 'snap_name'
        }
        self.work_flow.add(vnx_taskflow.ModifySnapshotTask())
        engine = taskflow.engines.load(self.work_flow,
                                       store=store_spec)
        self.assertRaises(vnx_ex.VNXSnapError,
                          engine.run)

    @res_mock.patch_client
    def test_create_cg_snapshot_task(self, client, mocked):
        store_spec = {
            'client': client,
            'cg_name': 'test_cg',
            'cg_snap_name': 'my_snap_name'
        }
        self.work_flow.add(vnx_taskflow.CreateCGSnapshotTask())
        engine = taskflow.engines.load(self.work_flow,
                                       store=store_spec)
        engine.run()
        snap_name = engine.storage.fetch('new_cg_snap_name')
        self.assertIsInstance(snap_name, res_mock.StorageObjectMock)

    @res_mock.patch_client
    def test_create_cg_snapshot_task_revert(self, client, mocked):
        store_spec = {
            'client': client,
            'cg_name': 'test_cg',
            'cg_snap_name': 'my_snap_name'
        }
        self.work_flow.add(vnx_taskflow.CreateCGSnapshotTask())
        engine = taskflow.engines.load(self.work_flow,
                                       store=store_spec)
        self.assertRaises(vnx_ex.VNXCreateSnapError,
                          engine.run)

    @res_mock.patch_client
    def test_extend_smp_task(self, client, mocked):
        store_spec = {
            'client': client,
            'smp_name': 'lun_test_extend_smp_task',
            'lun_size': 100
        }
        self.work_flow.add(vnx_taskflow.ExtendSMPTask())
        engine = taskflow.engines.load(self.work_flow,
                                       store=store_spec)
        engine.run()

    @res_mock.patch_client
    def test_extend_smp_task_skip_small_size(self, client, mocked):
        store_spec = {
            'client': client,
            'smp_name': 'lun_test_extend_smp_task',
            'lun_size': 1
        }
        self.work_flow.add(vnx_taskflow.ExtendSMPTask())
        engine = taskflow.engines.load(self.work_flow,
                                       store=store_spec)
        engine.run()

    @res_mock.patch_client
    def test_extend_smp_task_skip_thick(self, client, mocked):
        store_spec = {
            'client': client,
            'smp_name': 'lun_test_extend_smp_task_skip_thick',
            'lun_size': 100
        }
        self.work_flow.add(vnx_taskflow.ExtendSMPTask())
        engine = taskflow.engines.load(self.work_flow,
                                       store=store_spec)
        engine.run()
