# Copyright (C) 2016 EMC Corporation.
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

"""
Tests for group API.
"""
from unittest import mock

import ddt

from cinder import context
from cinder import exception
import cinder.group
from cinder import objects
from cinder.objects import fields
from cinder.policies import group_snapshots as g_snap_policies
from cinder import quota
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_volume
from cinder.tests.unit import test
from cinder.tests.unit import utils


GROUP_QUOTAS = quota.GROUP_QUOTAS


@ddt.ddt
class GroupAPITestCase(test.TestCase):
    """Test Case for group API."""

    def setUp(self):
        super(GroupAPITestCase, self).setUp()
        self.group_api = cinder.group.API()
        self.ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID,
                                           auth_token=True,
                                           is_admin=True)
        self.user_ctxt = context.RequestContext(
            fake.USER_ID, fake.PROJECT_ID, auth_token=True)

    @mock.patch('cinder.objects.Group.get_by_id')
    def test_get(self, mock_group_get):
        fake_group = {'name': 'fake_group'}
        mock_group_get.return_value = fake_group
        grp = self.group_api.get(self.ctxt, fake.GROUP_ID)
        self.assertEqual(fake_group, grp)

    @ddt.data(True, False)
    @mock.patch('cinder.objects.GroupList.get_all')
    @mock.patch('cinder.objects.GroupList.get_all_by_project')
    def test_get_all(self, is_admin, mock_get_all_by_project,
                     mock_get_all):
        self.group_api.LOG = mock.Mock()
        fake_groups = ['fake_group1', 'fake_group2']
        fake_groups_by_project = ['fake_group1']
        mock_get_all.return_value = fake_groups
        mock_get_all_by_project.return_value = fake_groups_by_project

        if is_admin:
            grps = self.group_api.get_all(self.ctxt,
                                          filters={'all_tenants': True})
            self.assertEqual(fake_groups, grps)
        else:
            grps = self.group_api.get_all(self.user_ctxt)
            self.assertEqual(fake_groups_by_project, grps)

    @mock.patch('cinder.volume.rpcapi.VolumeAPI.delete_group')
    @mock.patch('cinder.db.volume_get_all_by_generic_group')
    @mock.patch('cinder.db.volumes_update')
    @mock.patch('cinder.group.api.API._cast_create_group')
    @mock.patch('cinder.group.api.API.update_quota')
    @mock.patch('cinder.objects.Group')
    @mock.patch('cinder.db.group_type_get')
    @mock.patch('cinder.db.volume_types_get_by_name_or_id')
    def test_create_delete(self, mock_volume_types_get,
                           mock_group_type_get, mock_group,
                           mock_update_quota, mock_cast_create_group,
                           mock_volumes_update, mock_volume_get_all,
                           mock_rpc_delete_group):
        mock_volume_types_get.return_value = [{'id': fake.VOLUME_TYPE_ID}]
        mock_group_type_get.return_value = {'id': fake.GROUP_TYPE_ID}
        name = "test_group"
        description = "this is a test group"
        grp = utils.create_group(self.ctxt, group_type_id=fake.GROUP_TYPE_ID,
                                 volume_type_ids=[fake.VOLUME_TYPE_ID],
                                 availability_zone='nova', host=None,
                                 name=name, description=description,
                                 status=fields.GroupStatus.CREATING)
        mock_group.return_value = grp

        ret_group = self.group_api.create(self.ctxt, name, description,
                                          fake.GROUP_TYPE_ID,
                                          [fake.VOLUME_TYPE_ID],
                                          availability_zone='nova')
        self.assertEqual(grp.obj_to_primitive(), ret_group.obj_to_primitive())

        ret_group.host = "test_host@fakedrv#fakepool"
        ret_group.status = fields.GroupStatus.AVAILABLE
        ret_group.assert_not_frozen = mock.Mock(return_value=True)
        ret_group.group_snapshots = []
        self.group_api.delete(self.ctxt, ret_group, delete_volumes=True)
        mock_volume_get_all.assert_called_once_with(mock.ANY, ret_group.id)
        mock_volumes_update.assert_called_once_with(self.ctxt, [])
        mock_rpc_delete_group.assert_called_once_with(self.ctxt, ret_group)

    @mock.patch('cinder.group.api.API._cast_create_group')
    @mock.patch('cinder.group.api.API.update_quota')
    @mock.patch('cinder.objects.Group')
    @mock.patch('cinder.db.group_type_get_by_name')
    @mock.patch('cinder.db.volume_types_get_by_name_or_id')
    def test_create_with_group_name(self, mock_volume_types_get,
                                    mock_group_type_get, mock_group,
                                    mock_update_quota, mock_cast_create_group):
        mock_volume_types_get.return_value = [{'id': fake.VOLUME_TYPE_ID}]
        mock_group_type_get.return_value = {'id': fake.GROUP_TYPE_ID}
        name = "test_group"
        description = "this is a test group"
        grp = utils.create_group(self.ctxt, group_type_id=fake.GROUP_TYPE_ID,
                                 volume_type_ids=[fake.VOLUME_TYPE_ID],
                                 availability_zone='nova', host=None,
                                 name=name, description=description,
                                 status=fields.GroupStatus.CREATING)
        mock_group.return_value = grp

        ret_group = self.group_api.create(self.ctxt, name, description,
                                          "fake-grouptype-name",
                                          [fake.VOLUME_TYPE_ID],
                                          availability_zone='nova')
        self.assertEqual(grp.obj_to_primitive(), ret_group.obj_to_primitive())

        mock_group_type_get.assert_called_once_with(self.ctxt,
                                                    "fake-grouptype-name")

    @mock.patch('cinder.group.api.API._cast_create_group')
    @mock.patch('cinder.group.api.API.update_quota')
    @mock.patch('cinder.db.group_type_get')
    @mock.patch('cinder.db.group_type_get_by_name')
    @mock.patch('cinder.db.volume_types_get_by_name_or_id')
    def test_create_with_uuid_format_group_type_name(
            self, mock_volume_types_get, mock_group_type_get_by_name,
            mock_group_type_get, mock_update_quota, mock_cast_create_group):
        uuid_format_type_name = fake.UUID1
        mock_volume_types_get.return_value = [{'id': fake.VOLUME_TYPE_ID}]
        mock_group_type_get.side_effect = exception.GroupTypeNotFound(
            group_type_id=uuid_format_type_name)
        mock_group_type_get_by_name.return_value = {'id': fake.GROUP_TYPE_ID}

        ret_group = self.group_api.create(self.ctxt, "test_group", '',
                                          uuid_format_type_name,
                                          [fake.VOLUME_TYPE_ID],
                                          availability_zone='nova')
        self.assertEqual(ret_group["group_type_id"],
                         fake.GROUP_TYPE_ID)

    @mock.patch('cinder.group.api.API._cast_create_group')
    @mock.patch('cinder.group.api.API.update_quota')
    @mock.patch('cinder.db.group_type_get_by_name')
    @mock.patch('cinder.db.sqlalchemy.api._volume_type_get')
    @mock.patch('cinder.db.sqlalchemy.api._volume_type_get_by_name')
    def test_create_with_uuid_format_volume_type_name(
            self, mock_vol_t_get_by_name, mock_vol_types_get_by_id,
            mock_group_type_get, mock_update_quota, mock_cast_create_group):
        uuid_format_name = fake.UUID1
        mock_group_type_get.return_value = {'id': fake.GROUP_TYPE_ID}
        volume_type = {'id': fake.VOLUME_TYPE_ID, 'name': uuid_format_name}
        mock_vol_types_get_by_id.side_effect = exception.VolumeTypeNotFound(
            volume_type_id=uuid_format_name)
        mock_vol_t_get_by_name.return_value = volume_type
        group = self.group_api.create(self.ctxt, "test_group",
                                      "this is a test group",
                                      "fake-grouptype-name",
                                      [uuid_format_name],
                                      availability_zone='nova')
        self.assertEqual(group["volume_type_ids"],
                         [volume_type['id']])

    @mock.patch('cinder.group.api.API._cast_create_group')
    @mock.patch('cinder.group.api.API.update_quota')
    @mock.patch('cinder.db.group_type_get_by_name')
    @mock.patch('cinder.db.volume_types_get_by_name_or_id')
    def test_create_with_multi_types(self, mock_volume_types_get,
                                     mock_group_type_get,
                                     mock_update_quota,
                                     mock_cast_create_group):
        volume_types = [{'id': fake.VOLUME_TYPE_ID},
                        {'id': fake.VOLUME_TYPE2_ID}]
        mock_volume_types_get.return_value = volume_types
        mock_group_type_get.return_value = {'id': fake.GROUP_TYPE_ID}
        volume_type_names = ['fake-volume-type1', 'fake-volume-type2']
        name = "test_group"
        description = "this is a test group"

        group = self.group_api.create(self.ctxt, name, description,
                                      "fake-grouptype-name",
                                      volume_type_names,
                                      availability_zone='nova')
        self.assertEqual(group["volume_type_ids"],
                         [t['id'] for t in volume_types])
        self.assertEqual(group["group_type_id"], fake.GROUP_TYPE_ID)

        mock_group_type_get.assert_called_once_with(self.ctxt,
                                                    "fake-grouptype-name")
        mock_volume_types_get.assert_called_once_with(mock.ANY,
                                                      volume_type_names)

    @mock.patch('oslo_utils.timeutils.utcnow')
    @mock.patch('cinder.objects.Group')
    def test_reset_status(self, mock_group, mock_time_util):
        mock_time_util.return_value = "time_now"
        self.group_api.reset_status(self.ctxt, mock_group,
                                    fields.GroupStatus.AVAILABLE)

        update_field = {'updated_at': "time_now",
                        'status': fields.GroupStatus.AVAILABLE}
        mock_group.update.assert_called_once_with(update_field)
        mock_group.save.assert_called_once_with()

    @mock.patch.object(GROUP_QUOTAS, "reserve")
    @mock.patch('cinder.objects.Group')
    @mock.patch('cinder.db.group_type_get_by_name')
    @mock.patch('cinder.db.volume_types_get_by_name_or_id')
    def test_create_group_failed_update_quota(self,
                                              mock_volume_types_get,
                                              mock_group_type_get, mock_group,
                                              mock_group_quota_reserve):
        mock_volume_types_get.return_value = [{'id': fake.VOLUME_TYPE_ID}]
        mock_group_type_get.return_value = {'id': fake.GROUP_TYPE_ID}
        fake_overs = ['groups']
        fake_quotas = {'groups': 1}
        fake_usages = {'groups': {'reserved': 0, 'in_use': 1}}
        mock_group_quota_reserve.side_effect = exception.OverQuota(
            overs=fake_overs,
            quotas=fake_quotas,
            usages=fake_usages)
        name = "test_group"
        description = "this is a test group"
        grp = utils.create_group(self.ctxt, group_type_id=fake.GROUP_TYPE_ID,
                                 volume_type_ids=[fake.VOLUME_TYPE_ID],
                                 availability_zone='nova', host=None,
                                 name=name, description=description,
                                 status=fields.GroupStatus.CREATING)
        mock_group.return_value = grp

        self.assertRaises(exception.GroupLimitExceeded,
                          self.group_api.create,
                          self.ctxt, name, description,
                          "fake-grouptype-name",
                          [fake.VOLUME_TYPE_ID],
                          availability_zone='nova')

    @mock.patch('cinder.objects.Group')
    @mock.patch('cinder.db.volume_get')
    def test__validate_add_volumes(self, mock_volume_get, mock_group):
        grp = utils.create_group(self.ctxt, group_type_id=fake.GROUP_TYPE_ID,
                                 volume_type_ids=[fake.VOLUME_TYPE_ID],
                                 availability_zone='nova', host=None,
                                 name="name", description="description",
                                 status=fields.GroupStatus.CREATING)
        mock_group.return_value = grp
        fake_volume_obj = fake_volume.fake_volume_obj(self.ctxt)
        mock_volume_get.return_value = fake_volume_obj
        self.assertRaises(exception.InvalidVolume,
                          self.group_api._validate_add_volumes, self.ctxt,
                          [], ['123456789'], grp)

    @ddt.data(['test_host@fakedrv#fakepool', 'test_host@fakedrv#fakepool'],
              ['test_host@fakedrv#fakepool', 'test_host2@fakedrv#fakepool'])
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.update_group')
    @mock.patch('cinder.db.volume_get_all_by_generic_group')
    @mock.patch('cinder.group.api.API._cast_create_group')
    @mock.patch('cinder.group.api.API.update_quota')
    @mock.patch('cinder.objects.Group')
    @mock.patch('cinder.db.group_type_get')
    @mock.patch('cinder.db.volume_types_get_by_name_or_id')
    def test_update(self, hosts, mock_volume_types_get,
                    mock_group_type_get, mock_group,
                    mock_update_quota, mock_cast_create_group,
                    mock_volume_get_all, mock_rpc_update_group):
        vol_type_dict = {'id': fake.VOLUME_TYPE_ID,
                         'name': 'fake_volume_type'}
        vol_type = objects.VolumeType(self.ctxt, **vol_type_dict)

        mock_volume_types_get.return_value = [{'id': fake.VOLUME_TYPE_ID}]
        mock_group_type_get.return_value = {'id': fake.GROUP_TYPE_ID}
        name = "test_group"
        description = "this is a test group"
        grp = utils.create_group(self.ctxt, group_type_id=fake.GROUP_TYPE_ID,
                                 volume_type_ids=[fake.VOLUME_TYPE_ID],
                                 availability_zone='nova', host=None,
                                 name=name, description=description,
                                 status=fields.GroupStatus.CREATING)
        mock_group.return_value = grp

        ret_group = self.group_api.create(self.ctxt, name, description,
                                          fake.GROUP_TYPE_ID,
                                          [fake.VOLUME_TYPE_ID],
                                          availability_zone='nova')
        self.assertEqual(grp.obj_to_primitive(), ret_group.obj_to_primitive())

        ret_group.volume_types = [vol_type]
        ret_group.host = hosts[0]
        # set resource_backend directly because ret_group
        # is instance of MagicMock
        ret_group.resource_backend = 'fake-cluster'
        ret_group.status = fields.GroupStatus.AVAILABLE

        ret_group.id = fake.GROUP_ID

        vol1 = utils.create_volume(
            self.ctxt, host=hosts[1],
            availability_zone=ret_group.availability_zone,
            volume_type_id=fake.VOLUME_TYPE_ID,
            cluster_name='fake-cluster')

        vol2 = utils.create_volume(
            self.ctxt, host=hosts[1],
            availability_zone=ret_group.availability_zone,
            volume_type_id=fake.VOLUME_TYPE_ID,
            group_id=fake.GROUP_ID,
            cluster_name='fake-cluster')
        vol2_dict = {
            'id': vol2.id,
            'group_id': fake.GROUP_ID,
            'volume_type_id': fake.VOLUME_TYPE_ID,
            'availability_zone': ret_group.availability_zone,
            'host': hosts[1],
            'status': 'available',
        }
        mock_volume_get_all.return_value = [vol2_dict]

        new_name = "new_group_name"
        new_desc = "this is a new group"
        self.group_api.update(self.ctxt, ret_group, new_name, new_desc,
                              vol1.id, vol2.id)
        mock_volume_get_all.assert_called_once_with(mock.ANY, ret_group.id)
        mock_rpc_update_group.assert_called_once_with(self.ctxt, ret_group,
                                                      add_volumes=vol1.id,
                                                      remove_volumes=vol2.id)

    @mock.patch('cinder.objects.GroupSnapshot.get_by_id')
    @mock.patch('cinder.context.RequestContext.authorize')
    def test_get_group_snapshot(self, mock_authorize, mock_group_snap):
        fake_group_snap = 'fake_group_snap'
        mock_group_snap.return_value = fake_group_snap
        grp_snap = self.group_api.get_group_snapshot(
            self.ctxt, fake.GROUP_SNAPSHOT_ID)
        self.assertEqual(fake_group_snap, grp_snap)
        mock_authorize.assert_called_once_with(
            g_snap_policies.GET_POLICY,
            target_obj=fake_group_snap)

    @ddt.data(True, False)
    @mock.patch('cinder.objects.GroupSnapshotList.get_all')
    @mock.patch('cinder.objects.GroupSnapshotList.get_all_by_project')
    def test_get_all_group_snapshots(self, is_admin,
                                     mock_get_all_by_project,
                                     mock_get_all):
        fake_group_snaps = ['fake_group_snap1', 'fake_group_snap2']
        fake_group_snaps_by_project = ['fake_group_snap1']
        mock_get_all.return_value = fake_group_snaps
        mock_get_all_by_project.return_value = fake_group_snaps_by_project

        if is_admin:
            grp_snaps = self.group_api.get_all_group_snapshots(
                self.ctxt, filters={'all_tenants': True})
            self.assertEqual(fake_group_snaps, grp_snaps)
        else:
            grp_snaps = self.group_api.get_all_group_snapshots(
                self.user_ctxt)
            self.assertEqual(fake_group_snaps_by_project, grp_snaps)

    @mock.patch('cinder.objects.GroupSnapshot')
    def test_update_group_snapshot(self, mock_group_snap):
        grp_snap_update = {"name": "new_name",
                           "description": "This is a new description"}
        self.group_api.update_group_snapshot(self.ctxt, mock_group_snap,
                                             grp_snap_update)
        mock_group_snap.update.assert_called_once_with(grp_snap_update)
        mock_group_snap.save.assert_called_once_with()

    @mock.patch('cinder.volume.rpcapi.VolumeAPI.delete_group_snapshot')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.create_group_snapshot')
    @mock.patch('cinder.volume.api.API.create_snapshots_in_db')
    @mock.patch('cinder.objects.Group')
    @mock.patch('cinder.objects.GroupSnapshot')
    @mock.patch('cinder.objects.SnapshotList.get_all_for_group_snapshot')
    def test_create_delete_group_snapshot(self,
                                          mock_snap_get_all,
                                          mock_group_snap, mock_group,
                                          mock_create_in_db,
                                          mock_create_api, mock_delete_api):
        name = "fake_name"
        description = "fake description"
        mock_group.id = fake.GROUP_ID
        mock_group.group_type_id = fake.GROUP_TYPE_ID
        mock_group.assert_not_frozen = mock.Mock(return_value=True)
        mock_group.volumes = []
        ret_group_snap = self.group_api.create_group_snapshot(
            self.ctxt, mock_group, name, description)
        mock_snap_get_all.return_value = []

        options = {'group_id': fake.GROUP_ID,
                   'user_id': self.ctxt.user_id,
                   'project_id': self.ctxt.project_id,
                   'status': "creating",
                   'name': name,
                   'description': description,
                   'group_type_id': fake.GROUP_TYPE_ID}
        mock_group_snap.assert_called_once_with(self.ctxt, **options)
        ret_group_snap.create.assert_called_once_with()
        mock_create_in_db.assert_called_once_with(self.ctxt, [],
                                                  ret_group_snap.name,
                                                  ret_group_snap.description,
                                                  None,
                                                  ret_group_snap.id)
        mock_create_api.assert_called_once_with(self.ctxt, ret_group_snap)

        ret_group_snap.assert_not_frozen = mock.Mock(return_value=True)
        self.group_api.delete_group_snapshot(self.ctxt, ret_group_snap)
        mock_delete_api.assert_called_once_with(mock.ANY, ret_group_snap)

    @mock.patch('cinder.volume.api.API.delete')
    @mock.patch('cinder.objects.VolumeType.get_by_name_or_id')
    @mock.patch('cinder.db.group_volume_type_mapping_create')
    @mock.patch('cinder.volume.api.API.create')
    @mock.patch('cinder.objects.GroupSnapshot.get_by_id')
    @mock.patch('cinder.objects.SnapshotList.get_all_for_group_snapshot')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.create_group_from_src')
    @mock.patch('cinder.objects.VolumeList.get_all_by_generic_group')
    def test_create_group_from_snap_volume_failed(
            self, mock_volume_get_all,
            mock_rpc_create_group_from_src,
            mock_snap_get_all, mock_group_snap_get,
            mock_volume_api_create,
            mock_mapping_create,
            mock_get_volume_type, mock_volume_delete):
        mock_volume_api_create.side_effect = [exception.CinderException]
        vol_type = fake_volume.fake_volume_type_obj(
            self.ctxt,
            id=fake.VOLUME_TYPE_ID,
            name='fake_volume_type')
        mock_get_volume_type.return_value = vol_type

        grp_snap = utils.create_group_snapshot(
            self.ctxt, fake.GROUP_ID,
            group_type_id=fake.GROUP_TYPE_ID,
            status=fields.GroupStatus.CREATING)
        mock_group_snap_get.return_value = grp_snap
        vol1 = utils.create_volume(
            self.ctxt,
            availability_zone='nova',
            volume_type_id=vol_type['id'],
            group_id=fake.GROUP_ID)

        snap = utils.create_snapshot(self.ctxt, vol1.id,
                                     volume_type_id=vol_type['id'],
                                     status=fields.GroupStatus.CREATING)
        mock_snap_get_all.return_value = [snap]

        name = "test_group"
        description = "this is a test group"
        grp = utils.create_group(self.ctxt, group_type_id=fake.GROUP_TYPE_ID,
                                 volume_type_ids=[vol_type['id']],
                                 availability_zone='nova',
                                 name=name, description=description,
                                 group_snapshot_id=grp_snap.id,
                                 status=fields.GroupStatus.CREATING)

        vol2 = utils.create_volume(
            self.ctxt,
            availability_zone=grp.availability_zone,
            volume_type_id=vol_type['id'],
            group_id=grp.id,
            snapshot_id=snap.id)
        mock_volume_get_all.return_value = [vol2]

        self.assertRaises(
            exception.CinderException,
            self.group_api._create_group_from_group_snapshot,
            self.ctxt, grp, grp_snap.id)

        mock_volume_api_create.assert_called_once_with(
            self.ctxt, 1, None, None,
            availability_zone=grp.availability_zone,
            group_snapshot=grp_snap,
            group=grp,
            snapshot=snap,
            volume_type=vol_type)

        mock_rpc_create_group_from_src.assert_not_called()

        mock_volume_delete.assert_called_once_with(self.ctxt, vol2)

        vol2.destroy()
        grp.destroy()
        snap.destroy()
        vol1.destroy()
        grp_snap.destroy()

    @mock.patch('cinder.group.api.API._update_volumes_host')
    @mock.patch('cinder.objects.VolumeType.get_by_name_or_id')
    @mock.patch('cinder.db.group_volume_type_mapping_create')
    @mock.patch('cinder.volume.api.API.create')
    @mock.patch('cinder.objects.GroupSnapshot.get_by_id')
    @mock.patch('cinder.objects.SnapshotList.get_all_for_group_snapshot')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.create_group_from_src')
    @mock.patch('cinder.objects.VolumeList.get_all_by_generic_group')
    def test_create_group_from_snap(self, mock_volume_get_all,
                                    mock_rpc_create_group_from_src,
                                    mock_snap_get_all, mock_group_snap_get,
                                    mock_volume_api_create,
                                    mock_mapping_create,
                                    mock_get_volume_type,
                                    mock_update_volumes_host):
        vol_type = fake_volume.fake_volume_type_obj(
            self.ctxt,
            id=fake.VOLUME_TYPE_ID,
            name='fake_volume_type')
        mock_get_volume_type.return_value = vol_type

        grp_snap = utils.create_group_snapshot(
            self.ctxt, fake.GROUP_ID,
            group_type_id=fake.GROUP_TYPE_ID,
            status=fields.GroupStatus.CREATING)
        mock_group_snap_get.return_value = grp_snap
        vol1 = utils.create_volume(
            self.ctxt,
            availability_zone='nova',
            volume_type_id=vol_type['id'],
            group_id=fake.GROUP_ID)

        snap = utils.create_snapshot(self.ctxt, vol1.id,
                                     volume_type_id=vol_type['id'],
                                     status=fields.GroupStatus.CREATING)
        mock_snap_get_all.return_value = [snap]

        name = "test_group"
        description = "this is a test group"
        grp = utils.create_group(self.ctxt, group_type_id=fake.GROUP_TYPE_ID,
                                 volume_type_ids=[vol_type['id']],
                                 availability_zone='nova',
                                 name=name, description=description,
                                 group_snapshot_id=grp_snap.id,
                                 status=fields.GroupStatus.CREATING)

        vol2 = utils.create_volume(
            self.ctxt,
            availability_zone=grp.availability_zone,
            volume_type_id=vol_type['id'],
            group_id=grp.id,
            snapshot_id=snap.id)
        mock_volume_get_all.return_value = [vol2]

        self.group_api._create_group_from_group_snapshot(self.ctxt, grp,
                                                         grp_snap.id)

        mock_volume_api_create.assert_called_once_with(
            self.ctxt, 1, None, None,
            availability_zone=grp.availability_zone,
            group_snapshot=grp_snap,
            group=grp,
            snapshot=snap,
            volume_type=vol_type)

        mock_rpc_create_group_from_src.assert_called_once_with(
            self.ctxt, grp, grp_snap)

        mock_update_volumes_host.assert_called_once_with(
            self.ctxt, grp
        )

        vol2.destroy()
        grp.destroy()
        snap.destroy()
        vol1.destroy()
        grp_snap.destroy()

    @mock.patch('cinder.group.api.API._update_volumes_host')
    @mock.patch('cinder.objects.VolumeType.get_by_name_or_id')
    @mock.patch('cinder.db.group_volume_type_mapping_create')
    @mock.patch('cinder.volume.api.API.create')
    @mock.patch('cinder.objects.Group.get_by_id')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.create_group_from_src')
    @mock.patch('cinder.objects.VolumeList.get_all_by_generic_group')
    def test_create_group_from_group(self, mock_volume_get_all,
                                     mock_rpc_create_group_from_src,
                                     mock_group_get,
                                     mock_volume_api_create,
                                     mock_mapping_create,
                                     mock_get_volume_type,
                                     mock_update_volumes_host):
        vol_type = fake_volume.fake_volume_type_obj(
            self.ctxt,
            id=fake.VOLUME_TYPE_ID,
            name='fake_volume_type')
        mock_get_volume_type.return_value = vol_type

        grp = utils.create_group(self.ctxt, group_type_id=fake.GROUP_TYPE_ID,
                                 volume_type_ids=[vol_type['id']],
                                 availability_zone='nova',
                                 status=fields.GroupStatus.CREATING)
        mock_group_get.return_value = grp

        vol = utils.create_volume(
            self.ctxt,
            availability_zone=grp.availability_zone,
            volume_type_id=fake.VOLUME_TYPE_ID,
            group_id=grp.id)
        mock_volume_get_all.return_value = [vol]

        grp2 = utils.create_group(self.ctxt,
                                  group_type_id=fake.GROUP_TYPE_ID,
                                  volume_type_ids=[vol_type['id']],
                                  availability_zone='nova',
                                  source_group_id=grp.id,
                                  status=fields.GroupStatus.CREATING)

        vol2 = utils.create_volume(
            self.ctxt,
            availability_zone=grp.availability_zone,
            volume_type_id=vol_type['id'],
            group_id=grp2.id,
            source_volid=vol.id)

        self.group_api._create_group_from_source_group(self.ctxt, grp2,
                                                       grp.id)

        mock_volume_api_create.assert_called_once_with(
            self.ctxt, 1, None, None,
            availability_zone=grp.availability_zone,
            source_group=grp,
            group=grp2,
            source_volume=vol,
            volume_type=vol_type)

        mock_rpc_create_group_from_src.assert_called_once_with(
            self.ctxt, grp2, None, grp)

        mock_update_volumes_host.assert_called_once_with(
            self.ctxt, grp2
        )

        vol2.destroy()
        grp2.destroy()
        vol.destroy()
        grp.destroy()

    @mock.patch('cinder.volume.api.API.delete')
    @mock.patch('cinder.objects.VolumeType.get_by_name_or_id')
    @mock.patch('cinder.db.group_volume_type_mapping_create')
    @mock.patch('cinder.volume.api.API.create')
    @mock.patch('cinder.objects.Group.get_by_id')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.create_group_from_src')
    @mock.patch('cinder.objects.VolumeList.get_all_by_generic_group')
    def test_create_group_from_group_create_volume_failed(
            self, mock_volume_get_all, mock_rpc_create_group_from_src,
            mock_group_get, mock_volume_api_create, mock_mapping_create,
            mock_get_volume_type, mock_volume_delete):
        vol_type = fake_volume.fake_volume_type_obj(
            self.ctxt,
            id=fake.VOLUME_TYPE_ID,
            name='fake_volume_type')
        mock_get_volume_type.return_value = vol_type

        grp = utils.create_group(self.ctxt, group_type_id=fake.GROUP_TYPE_ID,
                                 volume_type_ids=[vol_type['id']],
                                 availability_zone='nova',
                                 status=fields.GroupStatus.CREATING)
        mock_group_get.return_value = grp

        vol1 = utils.create_volume(
            self.ctxt,
            availability_zone=grp.availability_zone,
            volume_type_id=fake.VOLUME_TYPE_ID,
            group_id=grp.id)
        vol2 = utils.create_volume(
            self.ctxt,
            availability_zone=grp.availability_zone,
            volume_type_id=fake.VOLUME_TYPE_ID,
            group_id=grp.id)
        mock_volume_get_all.side_effect = [[vol1, vol2], [vol1]]

        grp2 = utils.create_group(self.ctxt,
                                  group_type_id=fake.GROUP_TYPE_ID,
                                  volume_type_ids=[vol_type['id']],
                                  availability_zone='nova',
                                  source_group_id=grp.id,
                                  status=fields.GroupStatus.CREATING)

        mock_volume_api_create.side_effect = [None, exception.CinderException]

        self.assertRaises(
            exception.CinderException,
            self.group_api._create_group_from_source_group,
            self.ctxt, grp2, grp.id)

        mock_rpc_create_group_from_src.assert_not_called()
        mock_volume_delete.assert_called_once_with(self.ctxt, vol1)

        grp2.destroy()
        vol2.destroy()
        vol1.destroy()
        grp.destroy()

    @mock.patch('cinder.group.api.API._create_group_from_group_snapshot')
    @mock.patch('cinder.group.api.API._create_group_from_source_group')
    @mock.patch('cinder.group.api.API.update_quota')
    @mock.patch('cinder.objects.GroupSnapshot.get_by_id')
    @mock.patch('cinder.objects.SnapshotList.get_all_for_group_snapshot')
    @mock.patch('cinder.scheduler.rpcapi.SchedulerAPI.validate_host_capacity')
    def test_create_from_src(self, mock_validate_host, mock_snap_get_all,
                             mock_group_snap_get, mock_update_quota,
                             mock_create_from_group,
                             mock_create_from_snap):
        name = "test_group"
        description = "this is a test group"
        grp = utils.create_group(self.ctxt, group_type_id=fake.GROUP_TYPE_ID,
                                 volume_type_ids=[fake.VOLUME_TYPE_ID],
                                 availability_zone='nova',
                                 name=name, description=description,
                                 status=fields.GroupStatus.AVAILABLE,)

        vol1 = utils.create_volume(
            self.ctxt,
            availability_zone='nova',
            volume_type_id=fake.VOLUME_TYPE_ID,
            group_id=grp.id)

        snap = utils.create_snapshot(self.ctxt, vol1.id,
                                     volume_type_id=fake.VOLUME_TYPE_ID,
                                     status=fields.SnapshotStatus.AVAILABLE)
        mock_snap_get_all.return_value = [snap]
        mock_validate_host.return_host = True

        grp_snap = utils.create_group_snapshot(
            self.ctxt, grp.id,
            group_type_id=fake.GROUP_TYPE_ID,
            status=fields.GroupStatus.AVAILABLE)
        mock_group_snap_get.return_value = grp_snap

        grp2 = utils.create_group(self.ctxt,
                                  group_type_id=fake.GROUP_TYPE_ID,
                                  volume_type_ids=[fake.VOLUME_TYPE_ID],
                                  availability_zone='nova',
                                  name=name, description=description,
                                  status=fields.GroupStatus.CREATING,
                                  group_snapshot_id=grp_snap.id)

        with mock.patch('cinder.objects.Group') as mock_group:
            mock_group.return_value = grp2
            with mock.patch('cinder.objects.group.Group.create'):
                ret_group = self.group_api.create_from_src(
                    self.ctxt, name, description,
                    group_snapshot_id=grp_snap.id,
                    source_group_id=None)
                self.assertEqual(grp2.obj_to_primitive(),
                                 ret_group.obj_to_primitive())
                mock_create_from_snap.assert_called_once_with(
                    self.ctxt, grp2, grp_snap.id)

        snap.destroy()
        grp_snap.destroy()
        vol1.destroy()
        grp.destroy()
        grp2.destroy()

    @mock.patch('oslo_utils.timeutils.utcnow')
    @mock.patch('cinder.objects.GroupSnapshot')
    def test_reset_group_snapshot_status(self,
                                         mock_group_snapshot,
                                         mock_time_util):
        mock_time_util.return_value = "time_now"
        self.group_api.reset_group_snapshot_status(
            self.ctxt, mock_group_snapshot, fields.GroupSnapshotStatus.ERROR)

        update_field = {'updated_at': "time_now",
                        'status': fields.GroupSnapshotStatus.ERROR}
        mock_group_snapshot.update.assert_called_once_with(update_field)
        mock_group_snapshot.save.assert_called_once_with()

    @mock.patch('cinder.scheduler.rpcapi.SchedulerAPI.validate_host_capacity')
    def test_create_group_from_src_frozen(self, mock_validate_host):
        service = utils.create_service(self.ctxt, {'frozen': True})
        group = utils.create_group(self.ctxt, host=service.host,
                                   group_type_id='gt')
        mock_validate_host.return_value = True
        group_api = cinder.group.api.API()
        self.assertRaises(exception.InvalidInput,
                          group_api.create_from_src,
                          self.ctxt, 'group', 'desc',
                          group_snapshot_id=None, source_group_id=group.id)

    @mock.patch('cinder.objects.volume.Volume.host',
                new_callable=mock.PropertyMock)
    @mock.patch('cinder.objects.volume.Volume.cluster_name',
                new_callable=mock.PropertyMock)
    @mock.patch('cinder.objects.VolumeList.get_all_by_generic_group')
    def test_update_volumes_host(self, mock_volume_get_all, mock_cluster_name,
                                 mock_host):
        vol_type = utils.create_volume_type(self.ctxt, name='test_vol_type')
        grp = utils.create_group(self.ctxt, group_type_id=fake.GROUP_TYPE_ID,
                                 volume_type_ids=[vol_type['id']],
                                 availability_zone='nova',
                                 status=fields.GroupStatus.CREATING,
                                 cluster_name='fake_cluster')

        vol1 = utils.create_volume(
            self.ctxt,
            availability_zone=grp.availability_zone,
            volume_type_id=fake.VOLUME_TYPE_ID,
            group_id=grp.id)

        mock_volume = mock.Mock()
        mock_volume_get_all.return_value = [mock_volume]
        group_api = cinder.group.api.API()
        group_api._update_volumes_host(None, grp)

        mock_cluster_name.assert_called()
        mock_host.assert_called()

        self.assertEqual(grp.host, mock_volume.host)
        self.assertEqual(grp.cluster_name, mock_volume.cluster_name)
        mock_volume.save.assert_called_once_with()

        vol1.destroy()

        grp.destroy()

    def test_delete_group_frozen(self):
        service = utils.create_service(self.ctxt, {'frozen': True})
        group = utils.create_group(self.ctxt, host=service.host,
                                   group_type_id='gt')
        group_api = cinder.group.api.API()
        self.assertRaises(exception.InvalidInput,
                          group_api.delete, self.ctxt, group)

    def test_create_group_snapshot_frozen(self):
        service = utils.create_service(self.ctxt, {'frozen': True})
        group = utils.create_group(self.ctxt, host=service.host,
                                   group_type_id='gt')
        group_api = cinder.group.api.API()
        self.assertRaises(exception.InvalidInput,
                          group_api.create_group_snapshot,
                          self.ctxt, group, 'group_snapshot', 'desc')

    def test_delete_group_snapshot_frozen(self):
        service = utils.create_service(self.ctxt, {'frozen': True})
        group = utils.create_group(self.ctxt, host=service.host,
                                   group_type_id='gt')
        gsnap = utils.create_group_snapshot(self.ctxt, group.id)
        group_api = cinder.group.api.API()
        self.assertRaises(exception.InvalidInput,
                          group_api.delete_group_snapshot,
                          self.ctxt, gsnap)

    @mock.patch('cinder.volume.volume_types.get_volume_type_qos_specs',
                return_value={'qos_specs': {}})
    @mock.patch('cinder.scheduler.rpcapi.SchedulerAPI.create_group')
    def test_cast_create_group(self,
                               mock_create_group,
                               mock_get_volume_type_qos_specs):
        vol_type = utils.create_volume_type(self.ctxt, name='test_vol_type')
        encryption_key_id = mock.sentinel.encryption_key_id
        description = mock.sentinel.description
        name = mock.sentinel.name
        req_spec = {'volume_type': vol_type,
                    'encryption_key_id': encryption_key_id,
                    'description': description,
                    'name': name}

        grp_name = "test_group"
        grp_description = "this is a test group"
        grp_spec = {'name': grp_name,
                    'description': grp_description}

        grp = utils.create_group(self.ctxt,
                                 group_type_id=fake.GROUP_TYPE_ID,
                                 volume_type_ids=[vol_type.id],
                                 availability_zone='nova')

        grp_filter_properties = mock.sentinel.group_filter_properties
        filter_properties_list = mock.sentinel.filter_properties_list
        self.group_api._cast_create_group(self.ctxt,
                                          grp,
                                          grp_spec,
                                          [req_spec],
                                          grp_filter_properties,
                                          filter_properties_list)

        mock_get_volume_type_qos_specs.assert_called_once_with(vol_type.id)

        exp_vol_properties = {
            'size': 0,
            'user_id': self.ctxt.user_id,
            'project_id': self.ctxt.project_id,
            'status': 'creating',
            'attach_status': 'detached',
            'encryption_key_id': encryption_key_id,
            'display_description': description,
            'display_name': name,
            'volume_type_id': vol_type.id,
            'group_type_id': grp.group_type_id,
            'availability_zone': grp.availability_zone
        }
        exp_req_spec = {
            'volume_type': vol_type,
            'encryption_key_id': encryption_key_id,
            'description': description,
            'name': name,
            'volume_properties': exp_vol_properties,
            'qos_specs': None
        }
        exp_grp_properties = {
            'size': 0,
            'user_id': self.ctxt.user_id,
            'project_id': self.ctxt.project_id,
            'status': 'creating',
            'display_description': grp_description,
            'display_name': grp_name,
            'group_type_id': grp.group_type_id,
        }
        exp_grp_spec = {
            'name': grp_name,
            'description': grp_description,
            'volume_properties': exp_grp_properties,
            'qos_specs': None
        }
        mock_create_group.assert_called_once_with(
            self.ctxt,
            grp,
            group_spec=exp_grp_spec,
            request_spec_list=[exp_req_spec],
            group_filter_properties=grp_filter_properties,
            filter_properties_list=filter_properties_list)
