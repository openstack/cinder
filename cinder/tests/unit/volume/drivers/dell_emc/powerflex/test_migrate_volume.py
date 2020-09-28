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

from unittest import mock

import ddt
from oslo_service import loopingcall
import six

from cinder import context
from cinder import exception
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_volume
from cinder.tests.unit.volume.drivers.dell_emc import powerflex


MIGRATE_VOLUME_PARAMS_CASES = (
    # Cases for testing _get_volume_params function.
    # +----------------------------------------------------+------------------+
    # |Volume Type|Real provisioning|Conversion|Compression|Pool support thick|
    # +-----------+-----------------+----------+-----------+-----+------------+
    ('ThinProvisioned', 'ThinProvisioned', 'NoConversion', 'None', False),
    ('ThinProvisioned', 'ThickProvisioned', 'ThickToThin', 'None', True),
    ('ThickProvisioned', 'ThinProvisioned', 'NoConversion', 'None', False),
    ('ThickProvisioned', 'ThinProvisioned', 'ThinToThick', 'None', True),
    ('ThinProvisioned', 'ThinProvisioned', 'NoConversion', 'Normal', False),
    ('ThinProvisioned', 'ThickProvisioned', 'ThickToThin', 'Normal', False),
    ('ThinProvisioned', 'ThickProvisioned', 'ThickToThin', 'None', False)
)


@ddt.ddt
class TestMigrateVolume(powerflex.TestPowerFlexDriver):
    """Test cases for ``PowerFlexDriver.migrate_volume()``"""

    def setUp(self):
        """Setup a test case environment.

        Creates a fake volume object and sets up the required API responses.
        """

        super(TestMigrateVolume, self).setUp()
        ctx = context.RequestContext('fake', 'fake', auth_token=True)
        host = 'host@backend#{}:{}'.format(
            self.PROT_DOMAIN_NAME,
            self.STORAGE_POOL_NAME)
        self.volume = fake_volume.fake_volume_obj(
            ctx, **{'provider_id': fake.PROVIDER_ID, 'host': host,
                    'volume_type_id': fake.VOLUME_TYPE_ID})
        self.dst_host = {'host': host}
        self.DST_STORAGE_POOL_NAME = 'SP2'
        self.DST_STORAGE_POOL_ID = six.text_type('2')
        self.fake_vtree_id = 'c075744900000001'
        self.migration_success = (True, {})
        self.migration_host_assisted = (False, None)

        self.HTTPS_MOCK_RESPONSES = {
            self.RESPONSE_MODE.Valid: {
                'types/Domain/instances/getByName::{}'.format(
                    self.PROT_DOMAIN_NAME
                ): '"{}"'.format(self.PROT_DOMAIN_ID),
                'types/Pool/instances/getByName::{},{}'.format(
                    self.PROT_DOMAIN_ID,
                    self.STORAGE_POOL_NAME
                ): '"{}"'.format(self.STORAGE_POOL_ID),
                'types/Pool/instances/getByName::{},{}'.format(
                    self.PROT_DOMAIN_ID,
                    self.DST_STORAGE_POOL_NAME
                ): '"{}"'.format(self.DST_STORAGE_POOL_ID),
                'instances/ProtectionDomain::{}'.format(
                    self.PROT_DOMAIN_ID
                ): {'id': self.PROT_DOMAIN_ID},
                'instances/StoragePool::{}'.format(
                    self.STORAGE_POOL_ID
                ): {'id': self.STORAGE_POOL_ID,
                    'zeroPaddingEnabled': True},
                'instances/StoragePool::{}'.format(
                    self.DST_STORAGE_POOL_ID
                ): {'id': self.DST_STORAGE_POOL_ID,
                    'zeroPaddingEnabled': True},
                'instances/Volume::{}'.format(
                    self.volume.provider_id
                ): {'volumeType': 'ThinProvisioned',
                    'vtreeId': self.fake_vtree_id},
                'instances/Volume::{}/action/migrateVTree'.format(
                    self.volume.provider_id
                ): {},
                'instances/VTree::{}'.format(
                    self.fake_vtree_id
                ): {'vtreeMigrationInfo': {
                    'migrationStatus': 'NotInMigration',
                    'migrationPauseReason': None}}
            },
            self.RESPONSE_MODE.Invalid: {
                'instances/Volume::{}'.format(
                    self.volume.provider_id
                ): {'vtreeId': self.fake_vtree_id},
                'instances/VTree::{}'.format(
                    self.fake_vtree_id
                ): {'vtreeMigrationInfo': {'migrationPauseReason': None}}
            },
            self.RESPONSE_MODE.BadStatus: {
                'instances/Volume::{}/action/migrateVTree'.format(
                    self.volume.provider_id
                ): self.BAD_STATUS_RESPONSE
            },
        }

        self.volumetype_extraspecs_mock = self.mock_object(
            self.driver, '_get_volumetype_extraspecs',
            return_value={'provisioning:type': 'thin'}
        )

        self.volume_is_replicated_mock = self.mock_object(
            self.volume, 'is_replicated',
            return_value=False
        )

    def test_migrate_volume(self):
        ret = self.driver.migrate_volume(None, self.volume, self.dst_host)
        self.assertEqual(self.migration_success, ret)

    def test_migrate_replicated_volume(self):
        self.volume_is_replicated_mock.return_value = True
        self.assertRaises(exception.InvalidVolume,
                          self.driver.migrate_volume,
                          None, self.volume, self.dst_host)

    def test_migrate_volume_crossbackend_not_supported(self):
        dst_host = {'host': 'host@another_backend#PD1:P1'}
        ret = self.driver.migrate_volume(None, self.volume, dst_host)
        self.assertEqual(self.migration_host_assisted, ret)

    def test_migrate_volume_bad_status_response(self):
        with self.custom_response_mode(
                **{'instances/Volume::{}/action/migrateVTree'.format(
                    self.volume.provider_id): self.RESPONSE_MODE.BadStatus}
        ):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.driver.migrate_volume,
                              None, self.volume, self.dst_host)

    def test_migrate_volume_migration_in_progress(self):
        with self.custom_response_mode(
                **{'instances/Volume::{}/action/migrateVTree'.format(
                    self.volume.provider_id):
                        powerflex.mocks.MockHTTPSResponse(
                {
                    'errorCode': 717,
                    'message': 'Migration in progress',
                }, 500)}
        ):
            ret = self.driver.migrate_volume(None, self.volume, self.dst_host)
            self.assertEqual(self.migration_success, ret)

    @mock.patch(
        'cinder.volume.drivers.dell_emc.powerflex.driver.PowerFlexDriver.'
        '_wait_for_volume_migration_to_complete',
        side_effect=loopingcall.LoopingCallTimeOut()
    )
    def test_migrate_volume_migration_in_progress_timeout_expired(self, m):
        _, upd = self.driver.migrate_volume(None, self.volume, self.dst_host)
        self.assertEqual('maintenance', upd['status'])

    def test_migrate_volume_migration_failed(self):
        with self.custom_response_mode(
                **{'instances/VTree::{}'.format(self.fake_vtree_id):
                    powerflex.mocks.MockHTTPSResponse(
                        {'vtreeMigrationInfo':
                            {'migrationStatus': 'NotInMigration',
                             'migrationPauseReason': 'MigrationError'}}, 200)}
        ):
            self.assertRaises(exception.VolumeMigrationFailed,
                              self.driver.migrate_volume,
                              None, self.volume, self.dst_host)

    def test_get_real_provisioning_and_vtree_malformed_response(self):
        self.set_https_response_mode(self.RESPONSE_MODE.Invalid)
        self.assertRaises(exception.MalformedResponse,
                          self.driver._get_real_provisioning_and_vtree,
                          self.volume.provider_id)

    def test_wait_for_volume_migration_to_complete_malformed_response(self):
        self.set_https_response_mode(self.RESPONSE_MODE.Invalid)
        self.assertRaises(exception.MalformedResponse,
                          self.driver._wait_for_volume_migration_to_complete,
                          self.fake_vtree_id, self.volume.provider_id)

    @ddt.data(*MIGRATE_VOLUME_PARAMS_CASES)
    def test_get_migrate_volume_params(self, data):
        (vol_type,
         real_prov,
         conversion,
         compression,
         sup_thick) = data
        self.mock_object(self.driver, '_get_provisioning_and_compression',
                         return_value=(vol_type, compression))
        self.mock_object(self.driver, '_check_pool_support_thick_vols',
                         return_value=sup_thick)
        domain_name, pool_name = (
            self.driver._extract_domain_and_pool_from_host(
                self.dst_host['host']
            )
        )
        ret = self.driver._get_volume_migration_params(self.volume,
                                                       domain_name,
                                                       pool_name,
                                                       real_prov)
        self.assertTrue(ret['volTypeConversion'] == conversion)
        self.assertTrue(ret['compressionMethod'] == compression)
