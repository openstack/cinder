# Copyright (C) 2015 EMC Corporation.
# Copyright (C) 2016 Pure Storage, Inc.
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

from tempest.common import waiters
from tempest import config
from tempest.lib.common.utils import data_utils
from tempest.lib import decorators

from cinder.tests.tempest.api.volume import base
from cinder.tests.tempest import cinder_clients

CONF = config.CONF


class ConsistencyGroupsV2Test(base.BaseVolumeTest):
    @classmethod
    def setup_clients(cls):
        cls._api_version = 2
        super(ConsistencyGroupsV2Test, cls).setup_clients()
        cls.admin_volume_client = cls.os_admin.volumes_v2_client

        manager = cinder_clients.Manager(cls.os_adm)
        cls.consistencygroups_adm_client = manager.consistencygroups_adm_client

    @classmethod
    def skip_checks(cls):
        super(ConsistencyGroupsV2Test, cls).skip_checks()
        if not CONF.volume_feature_enabled.consistency_group:
            raise cls.skipException("Cinder consistency group "
                                    "feature disabled")

    def _delete_consistencygroup(self, cg_id):
        self.consistencygroups_adm_client.delete_consistencygroup(cg_id)
        vols = self.admin_volume_client.list_volumes(detail=True)['volumes']
        for vol in vols:
            if vol['consistencygroup_id'] == cg_id:
                self.admin_volume_client.wait_for_resource_deletion(vol['id'])
        self.consistencygroups_adm_client.wait_for_consistencygroup_deletion(
            cg_id)

    def _delete_cgsnapshot(self, cgsnapshot_id, cg_id):
        self.consistencygroups_adm_client.delete_cgsnapshot(cgsnapshot_id)
        vols = self.admin_volume_client.list_volumes(detail=True)['volumes']
        snapshots = self.os_admin.snapshots_v2_client.list_snapshots(
            detail=True)['snapshots']
        for vol in vols:
            for snap in snapshots:
                if (vol['consistencygroup_id'] == cg_id and
                        vol['id'] == snap['volume_id']):
                    (self.snapshots_client.
                     wait_for_resource_deletion(snap['id']))
        self.consistencygroups_adm_client.wait_for_cgsnapshot_deletion(
            cgsnapshot_id)

    @decorators.idempotent_id('3fe776ba-ec1f-4e6c-8d78-4b14c3a7fc44')
    def test_consistencygroup_create_delete(self):
        # Create volume type
        name = data_utils.rand_name("volume-type")
        volume_type = self.os_admin.volume_types_v2_client.create_volume_type(
            name=name)['volume_type']

        # Create CG
        cg_name = data_utils.rand_name('CG')
        create_consistencygroup = (
            self.consistencygroups_adm_client.create_consistencygroup)
        cg = create_consistencygroup(volume_type['id'],
                                     name=cg_name)['consistencygroup']
        vol_name = data_utils.rand_name("volume")
        params = {'name': vol_name,
                  'volume_type': volume_type['id'],
                  'consistencygroup_id': cg['id'],
                  'size': CONF.volume.volume_size}

        # Create volume
        volume = self.admin_volume_client.create_volume(**params)['volume']

        waiters.wait_for_volume_resource_status(self.admin_volume_client,
                                                volume['id'], 'available')
        self.consistencygroups_adm_client.wait_for_consistencygroup_status(
            cg['id'], 'available')
        self.assertEqual(cg_name, cg['name'])

        # Get a given CG
        cg = self.consistencygroups_adm_client.show_consistencygroup(
            cg['id'])['consistencygroup']
        self.assertEqual(cg_name, cg['name'])

        # Get all CGs with detail
        cgs = self.consistencygroups_adm_client.list_consistencygroups(
            detail=True)['consistencygroups']
        self.assertIn((cg['name'], cg['id']),
                      [(m['name'], m['id']) for m in cgs])

        # Clean up
        self._delete_consistencygroup(cg['id'])
        self.os_admin.volume_types_v2_client.delete_volume_type(
            volume_type['id'])

    @decorators.idempotent_id('2134dd52-f333-4456-bb05-6cb0f009a44f')
    def test_consistencygroup_cgsnapshot_create_delete(self):
        # Create volume type
        name = data_utils.rand_name("volume-type")
        volume_type = self.admin_volume_types_client.create_volume_type(
            name=name)['volume_type']

        # Create CG
        cg_name = data_utils.rand_name('CG')
        create_consistencygroup = (
            self.consistencygroups_adm_client.create_consistencygroup)
        cg = create_consistencygroup(volume_type['id'],
                                     name=cg_name)['consistencygroup']
        vol_name = data_utils.rand_name("volume")
        params = {'name': vol_name,
                  'volume_type': volume_type['id'],
                  'consistencygroup_id': cg['id'],
                  'size': CONF.volume.volume_size}

        # Create volume
        volume = self.admin_volume_client.create_volume(**params)['volume']
        waiters.wait_for_volume_resource_status(self.admin_volume_client,
                                                volume['id'], 'available')
        self.consistencygroups_adm_client.wait_for_consistencygroup_status(
            cg['id'], 'available')
        self.assertEqual(cg_name, cg['name'])

        # Create cgsnapshot
        cgsnapshot_name = data_utils.rand_name('cgsnapshot')
        create_cgsnapshot = (
            self.consistencygroups_adm_client.create_cgsnapshot)
        cgsnapshot = create_cgsnapshot(cg['id'],
                                       name=cgsnapshot_name)['cgsnapshot']
        snapshots = self.os_admin.snapshots_v2_client.list_snapshots(
            detail=True)['snapshots']
        for snap in snapshots:
            if volume['id'] == snap['volume_id']:
                waiters.wait_for_volume_resource_status(
                    self.os_admin.snapshots_v2_client,
                    snap['id'], 'available')
        self.consistencygroups_adm_client.wait_for_cgsnapshot_status(
            cgsnapshot['id'], 'available')
        self.assertEqual(cgsnapshot_name, cgsnapshot['name'])

        # Get a given CG snapshot
        cgsnapshot = self.consistencygroups_adm_client.show_cgsnapshot(
            cgsnapshot['id'])['cgsnapshot']
        self.assertEqual(cgsnapshot_name, cgsnapshot['name'])

        # Get all CG snapshots with detail
        cgsnapshots = self.consistencygroups_adm_client.list_cgsnapshots(
            detail=True)['cgsnapshots']
        self.assertIn((cgsnapshot['name'], cgsnapshot['id']),
                      [(m['name'], m['id']) for m in cgsnapshots])

        # Clean up
        self._delete_cgsnapshot(cgsnapshot['id'], cg['id'])
        self._delete_consistencygroup(cg['id'])
        self.admin_volume_types_client.delete_volume_type(volume_type['id'])

    @decorators.idempotent_id('3a6a5525-25ca-4a6c-aac4-cac6fa8f5b43')
    def test_create_consistencygroup_from_cgsnapshot(self):
        # Create volume type
        name = data_utils.rand_name("volume-type")
        volume_type = self.admin_volume_types_client.create_volume_type(
            name=name)['volume_type']

        # Create CG
        cg_name = data_utils.rand_name('CG')
        create_consistencygroup = (
            self.consistencygroups_adm_client.create_consistencygroup)
        cg = create_consistencygroup(volume_type['id'],
                                     name=cg_name)['consistencygroup']
        vol_name = data_utils.rand_name("volume")
        params = {'name': vol_name,
                  'volume_type': volume_type['id'],
                  'consistencygroup_id': cg['id'],
                  'size': CONF.volume.volume_size}

        # Create volume
        volume = self.admin_volume_client.create_volume(**params)['volume']
        waiters.wait_for_volume_resource_status(self.admin_volume_client,
                                                volume['id'], 'available')
        self.consistencygroups_adm_client.wait_for_consistencygroup_status(
            cg['id'], 'available')
        self.assertEqual(cg_name, cg['name'])

        # Create cgsnapshot
        cgsnapshot_name = data_utils.rand_name('cgsnapshot')
        create_cgsnapshot = (
            self.consistencygroups_adm_client.create_cgsnapshot)
        cgsnapshot = create_cgsnapshot(cg['id'],
                                       name=cgsnapshot_name)['cgsnapshot']
        snapshots = self.snapshots_client.list_snapshots(
            detail=True)['snapshots']
        for snap in snapshots:
            if volume['id'] == snap['volume_id']:
                waiters.wait_for_volume_resource_status(
                    self.os_admin.snapshots_v2_client, snap['id'], 'available')
        self.consistencygroups_adm_client.wait_for_cgsnapshot_status(
            cgsnapshot['id'], 'available')
        self.assertEqual(cgsnapshot_name, cgsnapshot['name'])

        # Create CG from CG snapshot
        cg_name2 = data_utils.rand_name('CG_from_snap')
        create_consistencygroup2 = (
            self.consistencygroups_adm_client.create_consistencygroup_from_src)
        cg2 = create_consistencygroup2(cgsnapshot_id=cgsnapshot['id'],
                                       name=cg_name2)['consistencygroup']
        vols = self.admin_volume_client.list_volumes(
            detail=True)['volumes']
        for vol in vols:
            if vol['consistencygroup_id'] == cg2['id']:
                waiters.wait_for_volume_resource_status(
                    self.admin_volume_client, vol['id'], 'available')
        self.consistencygroups_adm_client.wait_for_consistencygroup_status(
            cg2['id'], 'available')
        self.assertEqual(cg_name2, cg2['name'])

        # Clean up
        self._delete_consistencygroup(cg2['id'])
        self._delete_cgsnapshot(cgsnapshot['id'], cg['id'])
        self._delete_consistencygroup(cg['id'])
        self.admin_volume_types_client.delete_volume_type(volume_type['id'])

    @decorators.idempotent_id('556121ae-de9c-4342-9897-e54260447a19')
    def test_create_consistencygroup_from_consistencygroup(self):
        # Create volume type
        name = data_utils.rand_name("volume-type")
        volume_type = self.admin_volume_types_client.create_volume_type(
            name=name)['volume_type']

        # Create CG
        cg_name = data_utils.rand_name('CG')
        create_consistencygroup = (
            self.consistencygroups_adm_client.create_consistencygroup)
        cg = create_consistencygroup(volume_type['id'],
                                     name=cg_name)['consistencygroup']
        vol_name = data_utils.rand_name("volume")
        params = {'name': vol_name,
                  'volume_type': volume_type['id'],
                  'consistencygroup_id': cg['id'],
                  'size': CONF.volume.volume_size}

        # Create volume
        volume = self.admin_volume_client.create_volume(**params)['volume']
        waiters.wait_for_volume_resource_status(self.admin_volume_client,
                                                volume['id'], 'available')
        self.consistencygroups_adm_client.wait_for_consistencygroup_status(
            cg['id'], 'available')
        self.assertEqual(cg_name, cg['name'])

        # Create CG from CG
        cg_name2 = data_utils.rand_name('CG_from_cg')
        create_consistencygroup2 = (
            self.consistencygroups_adm_client.create_consistencygroup_from_src)
        cg2 = create_consistencygroup2(source_cgid=cg['id'],
                                       name=cg_name2)['consistencygroup']
        vols = self.admin_volume_client.list_volumes(
            detail=True)['volumes']
        for vol in vols:
            if vol['consistencygroup_id'] == cg2['id']:
                waiters.wait_for_volume_resource_status(
                    self.admin_volume_client, vol['id'], 'available')
        self.consistencygroups_adm_client.wait_for_consistencygroup_status(
            cg2['id'], 'available')
        self.assertEqual(cg_name2, cg2['name'])

        # Clean up
        self._delete_consistencygroup(cg2['id'])
        self._delete_consistencygroup(cg['id'])
        self.admin_volume_types_client.delete_volume_type(volume_type['id'])
