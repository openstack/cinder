# Copyright (c) 2020 Dell Inc. or its subsidiaries.
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

from copy import deepcopy
import mock

from cinder import exception
from cinder import test
from cinder.tests.unit.volume.drivers.dell_emc.powermax import (
    powermax_data as tpd)
from cinder.tests.unit.volume.drivers.dell_emc.powermax import (
    powermax_fake_objects as tpfo)
from cinder.volume.drivers.dell_emc.powermax import iscsi
from cinder.volume.drivers.dell_emc.powermax import migrate
from cinder.volume.drivers.dell_emc.powermax import provision
from cinder.volume.drivers.dell_emc.powermax import rest
from cinder.volume import utils as volume_utils


class PowerMaxMigrateTest(test.TestCase):
    def setUp(self):
        self.data = tpd.PowerMaxData()
        volume_utils.get_max_over_subscription_ratio = mock.Mock()
        super(PowerMaxMigrateTest, self).setUp()
        configuration = tpfo.FakeConfiguration(
            None, 'MaskingTests', 1, 1, san_ip='1.1.1.1',
            san_login='smc', vmax_array=self.data.array, vmax_srp='SRP_1',
            san_password='smc', san_api_port=8443,
            vmax_port_groups=[self.data.port_group_name_f])
        rest.PowerMaxRest._establish_rest_session = mock.Mock(
            return_value=tpfo.FakeRequestsSession())
        driver = iscsi.PowerMaxISCSIDriver(configuration=configuration)
        self.driver = driver
        self.common = self.driver.common
        self.migrate = self.common.migrate

    def test_get_masking_view_component_dict_shared_format_1(self):
        """Test for get_masking_view_component_dict, legacy case 1."""
        component_dict = self.migrate.get_masking_view_component_dict(
            'OS-myhost-No_SLO-8970da0c-MV', 'SRP_1')
        self.assertEqual('OS', component_dict['prefix'])
        self.assertEqual('myhost', component_dict['host'])
        self.assertEqual('No_SLO', component_dict['no_slo'])
        self.assertEqual('-8970da0c', component_dict['uuid'])
        self.assertEqual('MV', component_dict['postfix'])

    def test_get_masking_view_component_dict_shared_format_2(self):
        """Test for get_masking_view_component_dict, legacy case 2."""
        component_dict = self.migrate.get_masking_view_component_dict(
            'OS-myhost-No_SLO-F-8970da0c-MV', 'SRP_1')
        self.assertEqual('OS', component_dict['prefix'])
        self.assertEqual('myhost', component_dict['host'])
        self.assertEqual('-F', component_dict['protocol'])
        self.assertEqual('No_SLO', component_dict['no_slo'])
        self.assertEqual('-8970da0c', component_dict['uuid'])
        self.assertEqual('MV', component_dict['postfix'])

    def test_get_masking_view_component_dict_shared_format_3(self):
        """Test for get_masking_view_component_dict, legacy case 3."""
        component_dict = self.migrate.get_masking_view_component_dict(
            'OS-myhost-SRP_1-Silver-NONE-74346a64-MV', 'SRP_1')
        self.assertEqual('OS', component_dict['prefix'])
        self.assertEqual('myhost', component_dict['host'])
        self.assertEqual('SRP_1', component_dict['srp'])
        self.assertEqual('Silver', component_dict['slo'])
        self.assertEqual('NONE', component_dict['workload'])
        self.assertEqual('-74346a64', component_dict['uuid'])
        self.assertEqual('MV', component_dict['postfix'])

    def test_get_masking_view_component_dict_shared_format_4(self):
        """Test for get_masking_view_component_dict, legacy case 4."""
        component_dict = self.migrate.get_masking_view_component_dict(
            'OS-myhost-SRP_1-Bronze-DSS-I-1b454e9f-MV', 'SRP_1')
        self.assertEqual('OS', component_dict['prefix'])
        self.assertEqual('myhost', component_dict['host'])
        self.assertEqual('SRP_1', component_dict['srp'])
        self.assertEqual('Bronze', component_dict['slo'])
        self.assertEqual('DSS', component_dict['workload'])
        self.assertEqual('-I', component_dict['protocol'])
        self.assertEqual('-1b454e9f', component_dict['uuid'])
        self.assertEqual('MV', component_dict['postfix'])

    def test_get_masking_view_component_dict_non_shared_format_5(self):
        """Test for get_masking_view_component_dict, legacy case 5."""
        component_dict = self.migrate.get_masking_view_component_dict(
            'OS-myhost-No_SLO-MV', 'SRP_1')
        self.assertEqual('OS', component_dict['prefix'])
        self.assertEqual('myhost', component_dict['host'])
        self.assertEqual('No_SLO', component_dict['no_slo'])
        self.assertEqual('MV', component_dict['postfix'])

    def test_get_masking_view_component_dict_non_shared_format_6(self):
        """Test for get_masking_view_component_dict, legacy case 6."""
        component_dict = self.migrate.get_masking_view_component_dict(
            'OS-myhost-No_SLO-F-MV', 'SRP_1')
        self.assertEqual('OS', component_dict['prefix'])
        self.assertEqual('myhost', component_dict['host'])
        self.assertEqual('No_SLO', component_dict['no_slo'])
        self.assertEqual('-F', component_dict['protocol'])
        self.assertEqual('MV', component_dict['postfix'])

    def test_get_masking_view_component_dict_non_shared_format_7(self):
        """Test for get_masking_view_component_dict, legacy case 7."""
        component_dict = self.migrate.get_masking_view_component_dict(
            'OS-myhost-SRP_1-Diamond-OLTP-MV', 'SRP_1')
        self.assertEqual('OS', component_dict['prefix'])
        self.assertEqual('myhost', component_dict['host'])
        self.assertEqual('SRP_1', component_dict['srp'])
        self.assertEqual('Diamond', component_dict['slo'])
        self.assertEqual('OLTP', component_dict['workload'])
        self.assertEqual('MV', component_dict['postfix'])

    def test_get_masking_view_component_dict_non_shared_format_8(self):
        """Test for get_masking_view_component_dict, legacy case 8."""
        component_dict = self.migrate.get_masking_view_component_dict(
            'OS-myhost-SRP_1-Gold-NONE-F-MV', 'SRP_1')
        self.assertEqual('OS', component_dict['prefix'])
        self.assertEqual('myhost', component_dict['host'])
        self.assertEqual('SRP_1', component_dict['srp'])
        self.assertEqual('Gold', component_dict['slo'])
        self.assertEqual('NONE', component_dict['workload'])
        self.assertEqual('-F', component_dict['protocol'])
        self.assertEqual('MV', component_dict['postfix'])

    def test_get_masking_view_component_dict_host_with_dashes_no_slo(
            self):
        """Test for get_masking_view_component_dict, dashes in host."""
        component_dict = self.migrate.get_masking_view_component_dict(
            'OS-host-with-dashes-No_SLO-I-MV', 'SRP_1')
        self.assertEqual('OS', component_dict['prefix'])
        self.assertEqual('host-with-dashes', component_dict['host'])
        self.assertEqual('No_SLO', component_dict['no_slo'])
        self.assertEqual('-I', component_dict['protocol'])
        self.assertEqual('MV', component_dict['postfix'])

    def test_get_masking_view_component_dict_host_with_dashes_slo(self):
        """Test for get_masking_view_component_dict, dashes and slo."""
        component_dict = self.migrate.get_masking_view_component_dict(
            'OS-host-with-dashes-SRP_1-Diamond-NONE-I-MV', 'SRP_1')
        self.assertEqual('OS', component_dict['prefix'])
        self.assertEqual('host-with-dashes', component_dict['host'])
        self.assertEqual('SRP_1', component_dict['srp'])
        self.assertEqual('Diamond', component_dict['slo'])
        self.assertEqual('NONE', component_dict['workload'])
        self.assertEqual('-I', component_dict['protocol'])
        self.assertEqual('MV', component_dict['postfix'])

    def test_get_masking_view_component_dict_replication_enabled(self):
        """Test for get_masking_view_component_dict, replication enabled."""
        component_dict = self.migrate.get_masking_view_component_dict(
            'OS-myhost-SRP_1-Diamond-OLTP-I-RE-MV', 'SRP_1')
        self.assertEqual('OS', component_dict['prefix'])
        self.assertEqual('myhost', component_dict['host'])
        self.assertEqual('-I', component_dict['protocol'])
        self.assertEqual('Diamond', component_dict['slo'])
        self.assertEqual('OLTP', component_dict['workload'])
        self.assertEqual('-RE', component_dict['RE'])

    def test_get_masking_view_component_dict_compression_disabled(self):
        """Test for get_masking_view_component_dict, compression disabled."""
        component_dict = self.migrate.get_masking_view_component_dict(
            'OS-myhost-SRP_1-Bronze-DSS_REP-I-CD-MV', 'SRP_1')
        self.assertEqual('OS', component_dict['prefix'])
        self.assertEqual('myhost', component_dict['host'])
        self.assertEqual('-I', component_dict['protocol'])
        self.assertEqual('Bronze', component_dict['slo'])
        self.assertEqual('DSS_REP', component_dict['workload'])
        self.assertEqual('-CD', component_dict['CD'])

    def test_get_masking_view_component_dict_CD_RE(self):
        """Test for get_masking_view_component_dict, CD and RE."""
        component_dict = self.migrate.get_masking_view_component_dict(
            'OS-myhost-SRP_1-Platinum-OLTP_REP-I-CD-RE-MV', 'SRP_1')
        self.assertEqual('OS', component_dict['prefix'])
        self.assertEqual('myhost', component_dict['host'])
        self.assertEqual('-I', component_dict['protocol'])
        self.assertEqual('Platinum', component_dict['slo'])
        self.assertEqual('OLTP_REP', component_dict['workload'])
        self.assertEqual('-CD', component_dict['CD'])
        self.assertEqual('-RE', component_dict['RE'])

    @mock.patch.object(migrate.PowerMaxMigrate,
                       '_perform_migration',
                       return_value=True)
    @mock.patch.object(migrate.PowerMaxMigrate,
                       '_get_mvs_and_sgs_from_volume',
                       return_value=(tpd.PowerMaxData.legacy_mvs,
                                     [tpd.PowerMaxData.legacy_shared_sg]))
    @mock.patch.object(migrate.PowerMaxMigrate,
                       'get_volume_host_list',
                       return_value=['myhostB'])
    def test_do_migrate_if_candidate(
            self, mock_mvs, mock_os_host, mock_migrate):
        self.assertTrue(self.migrate.do_migrate_if_candidate(
            self.data.array, self.data.srp, self.data.device_id,
            self.data.test_volume, self.data.connector))

    @mock.patch.object(migrate.PowerMaxMigrate,
                       '_get_mvs_and_sgs_from_volume',
                       return_value=([tpd.PowerMaxData.legacy_not_shared_mv],
                                     [tpd.PowerMaxData.legacy_not_shared_sg]))
    def test_do_migrate_if_candidate_not_shared(
            self, mock_mvs):
        self.assertFalse(self.migrate.do_migrate_if_candidate(
            self.data.array, self.data.srp, self.data.device_id,
            self.data.test_volume, self.data.connector))

    @mock.patch.object(migrate.PowerMaxMigrate,
                       '_get_mvs_and_sgs_from_volume',
                       return_value=(tpd.PowerMaxData.legacy_mvs,
                                     [tpd.PowerMaxData.legacy_shared_sg,
                                      'non_fast_sg']))
    def test_do_migrate_if_candidate_in_multiple_sgs(
            self, mock_mvs):
        self.assertFalse(self.migrate.do_migrate_if_candidate(
            self.data.array, self.data.srp, self.data.device_id,
            self.data.test_volume, self.data.connector))

    @mock.patch.object(migrate.PowerMaxMigrate,
                       '_perform_migration',
                       return_value=True)
    @mock.patch.object(migrate.PowerMaxMigrate,
                       '_get_mvs_and_sgs_from_volume',
                       return_value=(tpd.PowerMaxData.legacy_mvs,
                                     [tpd.PowerMaxData.legacy_shared_sg]))
    @mock.patch.object(migrate.PowerMaxMigrate,
                       'get_volume_host_list',
                       return_value=['myhostA', 'myhostB'])
    def test_dp_migrate_if_candidate_multiple_os_hosts(
            self, mock_mvs, mock_os_host, mock_migrate):
        self.assertFalse(self.migrate.do_migrate_if_candidate(
            self.data.array, self.data.srp, self.data.device_id,
            self.data.test_volume, self.data.connector))

    @mock.patch.object(migrate.PowerMaxMigrate,
                       '_delete_staging_masking_views')
    @mock.patch.object(migrate.PowerMaxMigrate,
                       '_get_mvs_and_sgs_from_volume',
                       side_effect=[(tpd.PowerMaxData.staging_mvs,
                                     [tpd.PowerMaxData.staging_sg]),
                                    ([tpd.PowerMaxData.staging_mv2],
                                     [tpd.PowerMaxData.staging_sg])])
    @mock.patch.object(migrate.PowerMaxMigrate,
                       '_create_stg_masking_views',
                       return_value=tpd.PowerMaxData.staging_mvs)
    @mock.patch.object(migrate.PowerMaxMigrate,
                       '_create_stg_storage_group_with_vol',
                       return_value=tpd.PowerMaxData.staging_sg)
    def test_perform_migration(self, mock_sg, mock_mvs, mock_new, mock_del):
        """Test to perform migration"""
        source_sg_name = 'OS-myhost-SRP_1-Diamond-OLTP-F-SG'
        mv_details_list = list()
        mv_details_list.append(self.migrate.get_masking_view_component_dict(
            'OS-myhostA-SRP_1-Diamond-OLTP-F-1b454e9f-MV', 'SRP_1'))
        mv_details_list.append(self.migrate.get_masking_view_component_dict(
            'OS-myhostB-SRP_1-Diamond-OLTP-F-8970da0c-MV', 'SRP_1'))
        self.assertTrue(self.migrate._perform_migration(
            self.data.array, self.data.device_id, mv_details_list,
            source_sg_name, 'myhostB'))

    @mock.patch.object(migrate.PowerMaxMigrate,
                       '_create_stg_storage_group_with_vol',
                       return_value=None)
    def test_perform_migration_storage_group_fail(self, mock_sg):
        """Test to perform migration"""
        source_sg_name = 'OS-myhost-SRP_1-Diamond-OLTP-F-SG'
        mv_details_list = list()
        mv_details_list.append(self.migrate.get_masking_view_component_dict(
            'OS-myhostA-SRP_1-Diamond-OLTP-F-1b454e9f-MV', 'SRP_1'))
        mv_details_list.append(self.migrate.get_masking_view_component_dict(
            'OS-myhostB-SRP_1-Diamond-OLTP-F-8970da0c-MV', 'SRP_1'))
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.migrate._perform_migration, self.data.array,
            self.data.device_id, mv_details_list,
            source_sg_name, 'myhostB')
        with self.assertRaisesRegex(
                exception.VolumeBackendAPIException,
                'MIGRATE - Unable to create staging storage group.'):
            self.migrate._perform_migration(
                self.data.array, self.data.device_id, mv_details_list,
                source_sg_name, 'myhostB')

    @mock.patch.object(migrate.PowerMaxMigrate,
                       '_create_stg_masking_views',
                       return_value=[])
    @mock.patch.object(migrate.PowerMaxMigrate,
                       '_create_stg_storage_group_with_vol',
                       return_value=tpd.PowerMaxData.staging_sg)
    def test_perform_migration_masking_views_fail(self, mock_sg, mock_mvs):
        """Test to perform migration"""
        source_sg_name = 'OS-myhost-SRP_1-Diamond-OLTP-F-SG'
        mv_details_list = list()
        mv_details_list.append(self.migrate.get_masking_view_component_dict(
            'OS-myhostA-SRP_1-Diamond-OLTP-F-1b454e9f-MV', 'SRP_1'))
        mv_details_list.append(self.migrate.get_masking_view_component_dict(
            'OS-myhostB-SRP_1-Diamond-OLTP-F-8970da0c-MV', 'SRP_1'))
        with self.assertRaisesRegex(
                exception.VolumeBackendAPIException,
                'MIGRATE - Unable to create staging masking views.'):
            self.migrate._perform_migration(
                self.data.array, self.data.device_id, mv_details_list,
                source_sg_name, 'myhostB')

    @mock.patch.object(migrate.PowerMaxMigrate,
                       '_get_mvs_and_sgs_from_volume',
                       return_value=(tpd.PowerMaxData.staging_mvs,
                                     [tpd.PowerMaxData.staging_sg,
                                      tpd.PowerMaxData.staging_sg]))
    @mock.patch.object(migrate.PowerMaxMigrate,
                       '_create_stg_masking_views',
                       return_value=tpd.PowerMaxData.staging_mvs)
    @mock.patch.object(migrate.PowerMaxMigrate,
                       '_create_stg_storage_group_with_vol',
                       return_value=tpd.PowerMaxData.staging_sg)
    def test_perform_migration_sg_list_len_fail(
            self, mock_sg, mock_mvs, mock_new):
        """Test to perform migration"""
        source_sg_name = 'OS-myhost-SRP_1-Diamond-OLTP-F-SG'
        mv_details_list = list()
        mv_details_list.append(self.migrate.get_masking_view_component_dict(
            'OS-myhostA-SRP_1-Diamond-OLTP-F-1b454e9f-MV', 'SRP_1'))
        mv_details_list.append(self.migrate.get_masking_view_component_dict(
            'OS-myhostB-SRP_1-Diamond-OLTP-F-8970da0c-MV', 'SRP_1'))

        exception_message = (
            r"MIGRATE - The current storage group list has 2 "
            r"members. The list is "
            r"\[\'STG-myhostB-4732de9b-98a4-4b6d-ae4b-3cafb3d34220-SG\', "
            r"\'STG-myhostB-4732de9b-98a4-4b6d-ae4b-3cafb3d34220-SG\'\]. "
            r"Will not proceed with cleanup. Please contact customer "
            r"representative.")

        with self.assertRaisesRegex(
                exception.VolumeBackendAPIException,
                exception_message):
            self.migrate._perform_migration(
                self.data.array, self.data.device_id, mv_details_list,
                source_sg_name, 'myhostB')

    @mock.patch.object(migrate.PowerMaxMigrate,
                       '_get_mvs_and_sgs_from_volume',
                       return_value=(tpd.PowerMaxData.staging_mvs,
                                     ['not_staging_sg']))
    @mock.patch.object(migrate.PowerMaxMigrate,
                       '_create_stg_masking_views',
                       return_value=tpd.PowerMaxData.staging_mvs)
    @mock.patch.object(migrate.PowerMaxMigrate,
                       '_create_stg_storage_group_with_vol',
                       return_value=tpd.PowerMaxData.staging_sg)
    def test_perform_migration_stg_sg_mismatch_fail(
            self, mock_sg, mock_mvs, mock_new):
        """Test to perform migration"""
        source_sg_name = 'OS-myhost-SRP_1-Diamond-OLTP-F-SG'
        mv_details_list = list()
        mv_details_list.append(self.migrate.get_masking_view_component_dict(
            'OS-myhostA-SRP_1-Diamond-OLTP-F-1b454e9f-MV', 'SRP_1'))
        mv_details_list.append(self.migrate.get_masking_view_component_dict(
            'OS-myhostB-SRP_1-Diamond-OLTP-F-8970da0c-MV', 'SRP_1'))
        with self.assertRaisesRegex(
                exception.VolumeBackendAPIException,
                'MIGRATE - The current storage group not_staging_sg does not '
                'match STG-myhostB-4732de9b-98a4-4b6d-ae4b-3cafb3d34220-SG. '
                'Will not proceed with cleanup. Please contact customer '
                'representative.'):
            self.migrate._perform_migration(
                self.data.array, self.data.device_id, mv_details_list,
                source_sg_name, 'myhostB')

    @mock.patch.object(rest.PowerMaxRest, 'delete_masking_view')
    def test_delete_staging_masking_views(self, mock_del):
        self.assertTrue(self.migrate._delete_staging_masking_views(
            self.data.array, self.data.staging_mvs, 'myhostB'))
        mock_del.assert_called_once()

    @mock.patch.object(rest.PowerMaxRest, 'delete_masking_view')
    def test_delete_staging_masking_views_no_host_match(self, mock_del):
        self.assertFalse(self.migrate._delete_staging_masking_views(
            self.data.array, self.data.staging_mvs, 'myhostC'))
        mock_del.assert_not_called()

    @mock.patch.object(rest.PowerMaxRest, 'create_masking_view')
    @mock.patch.object(rest.PowerMaxRest, 'get_masking_view',
                       return_value=tpd.PowerMaxData.maskingview[0])
    def test_create_stg_masking_views(self, mock_get, mock_create):
        mv_detail_list = list()
        for masking_view in self.data.legacy_mvs:
            masking_view_dict = self.migrate.get_masking_view_component_dict(
                masking_view, 'SRP_1')
            if masking_view_dict:
                mv_detail_list.append(masking_view_dict)
        self.assertIsNotNone(self.migrate._create_stg_masking_views(
            self.data.array, mv_detail_list, self.data.staging_sg,
            self.data.extra_specs))
        self.assertEqual(2, mock_create.call_count)

    @mock.patch.object(rest.PowerMaxRest, 'create_masking_view')
    @mock.patch.object(rest.PowerMaxRest, 'get_masking_view',
                       side_effect=[tpd.PowerMaxData.maskingview[0], None])
    def test_create_stg_masking_views_mv_not_created(
            self, mock_get, mock_create):
        mv_detail_list = list()
        for masking_view in self.data.legacy_mvs:
            masking_view_dict = self.migrate.get_masking_view_component_dict(
                masking_view, 'SRP_1')
            if masking_view_dict:
                mv_detail_list.append(masking_view_dict)
        self.assertIsNone(self.migrate._create_stg_masking_views(
            self.data.array, mv_detail_list, self.data.staging_sg,
            self.data.extra_specs))

    @mock.patch.object(provision.PowerMaxProvision, 'create_volume_from_sg')
    @mock.patch.object(provision.PowerMaxProvision, 'create_storage_group',
                       return_value=tpd.PowerMaxData.staging_mvs[0])
    def test_create_stg_storage_group_with_vol(self, mock_mv, mock_create):
        self.migrate._create_stg_storage_group_with_vol(
            self.data.array, 'myhostB', self.data.extra_specs)
        mock_create.assert_called_once()

    @mock.patch.object(provision.PowerMaxProvision, 'create_volume_from_sg')
    @mock.patch.object(provision.PowerMaxProvision, 'create_storage_group',
                       return_value=None)
    def test_create_stg_storage_group_with_vol_None(
            self, mock_mv, mock_create):
        self.assertIsNone(self.migrate._create_stg_storage_group_with_vol(
            self.data.array, 'myhostB', self.data.extra_specs))

    @mock.patch.object(rest.PowerMaxRest,
                       'get_masking_views_from_storage_group',
                       return_value=tpd.PowerMaxData.legacy_mvs)
    @mock.patch.object(rest.PowerMaxRest, 'get_storage_groups_from_volume',
                       return_value=[tpd.PowerMaxData.legacy_shared_sg])
    def test_get_mvs_and_sgs_from_volume(self, mock_sgs, mock_mvs):
        mv_list, sg_list = self.migrate._get_mvs_and_sgs_from_volume(
            self.data.array, self.data.device_id)
        mock_mvs.assert_called_once()
        self.assertEqual([self.data.legacy_shared_sg], sg_list)
        self.assertEqual(self.data.legacy_mvs, mv_list)

    @mock.patch.object(rest.PowerMaxRest,
                       'get_masking_views_from_storage_group')
    @mock.patch.object(rest.PowerMaxRest, 'get_storage_groups_from_volume',
                       return_value=list())
    def test_get_mvs_and_sgs_from_volume_empty_sg_list(
            self, mock_sgs, mock_mvs):
        mv_list, sg_list = self.migrate._get_mvs_and_sgs_from_volume(
            self.data.array, self.data.device_id)
        mock_mvs.assert_not_called()
        self.assertTrue(len(sg_list) == 0)
        self.assertTrue(len(mv_list) == 0)

    def test_get_volume_host_list(self):
        volume1 = deepcopy(self.data.test_volume)
        volume1.volume_attachment.objects = [self.data.test_volume_attachment]
        os_host_list = self.migrate.get_volume_host_list(
            volume1, self.data.connector)
        self.assertEqual('HostX', os_host_list[0])

    def test_get_volume_host_list_no_attachments(self):
        _volume_attachment = deepcopy(self.data.test_volume_attachment)
        _volume_attachment.update({'connector': None})
        volume1 = deepcopy(self.data.test_volume)
        volume1.volume_attachment.objects = [_volume_attachment]
        os_host_list = self.migrate.get_volume_host_list(
            volume1, self.data.connector)
        self.assertTrue(len(os_host_list) == 0)

    @mock.patch.object(rest.PowerMaxRest,
                       'delete_masking_view')
    @mock.patch.object(rest.PowerMaxRest,
                       'get_masking_views_from_storage_group',
                       return_value=[tpd.PowerMaxData.staging_mv1])
    @mock.patch.object(rest.PowerMaxRest,
                       'get_volumes_in_storage_group',
                       return_value=[tpd.PowerMaxData.volume_id])
    def test_cleanup_staging_objects(self, mock_vols, mock_mvs, mock_del_mv):
        self.migrate.cleanup_staging_objects(
            self.data.array, [self.data.staging_sg], self.data.extra_specs)
        mock_del_mv.assert_called_once_with(
            self.data.array, self.data.staging_mv1)

    @mock.patch.object(rest.PowerMaxRest,
                       'delete_masking_view')
    def test_cleanup_staging_objects_not_staging(self, mock_del_mv):
        self.migrate.cleanup_staging_objects(
            self.data.array, [self.data.storagegroup_name_f],
            self.data.extra_specs)
        mock_del_mv.assert_not_called()

    @mock.patch.object(rest.PowerMaxRest,
                       'get_masking_views_from_storage_group')
    @mock.patch.object(rest.PowerMaxRest,
                       'get_volumes_in_storage_group',
                       return_value=[tpd.PowerMaxData.device_id,
                                     tpd.PowerMaxData.device_id2], )
    def test_cleanup_staging_objects_multiple_vols(self, mock_vols, mock_mvs):
        self.migrate.cleanup_staging_objects(
            self.data.array, [self.data.storagegroup_name_f],
            self.data.extra_specs)
        mock_mvs.assert_not_called()
