# Copyright (C) 2017 Dell Inc. or its subsidiaries.
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
from unittest import mock

import ddt

from cinder.tests.unit import fake_volume
from cinder.tests.unit.volume.drivers.dell_emc import powerflex


VOLUME_ID = "abcdabcd-1234-abcd-1234-abcdabcdabcd"
PROVIDER_ID = "0000000000000001"

MANAGEABLE_FLEX_VOLS = [
    {
        "volumeType": "ThinProvisioned",
        "storagePoolId": "6c6dc54500000000",
        "sizeInKb": 8388608,
        "name": "volume1",
        "id": PROVIDER_ID,
        "mappedSdcInfo": [],
    },
    {
        "volumeType": "ThinProvisioned",
        "storagePoolId": "6c6dc54500000000",
        "sizeInKb": 8388608,
        "name": "volume2",
        "id": "0000000000000002",
        "mappedSdcInfo": [],
    },
    {
        "volumeType": "ThickProvisioned",
        "storagePoolId": "6c6dc54500000000",
        "sizeInKb": 8388608,
        "name": "volume3",
        "id": "0000000000000003",
        "mappedSdcInfo": [],
    }
]

POWERFLEX_SNAPSHOT = {
    "volumeType": "Snapshot",
    "storagePoolId": "6c6dc54500000000",
    "sizeInKb": 8388608,
    "name": "snapshot1",
    "id": "1000000000000001",
    "mappedSdcInfo": [],
}

MANAGEABLE_FLEX_VOL_REFS = [
    {
        'reference': {'source-id': PROVIDER_ID},
        'size': 8,
        'safe_to_manage': True,
        'reason_not_safe': None,
        'cinder_id': None,
        'extra_info': {
            "volumeType": "ThinProvisioned",
            "name": "volume1"
        }
    },
    {
        'reference': {'source-id': '0000000000000002'},
        'size': 8,
        'safe_to_manage': True,
        'reason_not_safe': None,
        'cinder_id': None,
        'extra_info': {
            "volumeType": "ThinProvisioned",
            "name": "volume2"
        }
    },
    {
        'reference': {'source-id': '0000000000000003'},
        'size': 8,
        'safe_to_manage': True,
        'reason_not_safe': None,
        'cinder_id': None,
        'extra_info': {
            "volumeType": "ThickProvisioned",
            "name": "volume3"
        }
    }
]


@ddt.ddt
class PowerFlexManageableCase(powerflex.TestPowerFlexDriver):

    def setUp(self):
        """Setup a test case environment."""
        super(PowerFlexManageableCase, self).setUp()
        self.driver.storage_pools = super().STORAGE_POOLS

    def _test_get_manageable_things(self,
                                    powerflex_objects=MANAGEABLE_FLEX_VOLS,
                                    expected_refs=MANAGEABLE_FLEX_VOL_REFS,
                                    cinder_objs=list()):
        marker = mock.Mock()
        limit = mock.Mock()
        offset = mock.Mock()
        sort_keys = mock.Mock()
        sort_dirs = mock.Mock()

        self.HTTPS_MOCK_RESPONSES = {
            self.RESPONSE_MODE.Valid: {
                'instances/StoragePool::{}/relationships/Volume'.format(
                    self.STORAGE_POOL_ID
                ): powerflex_objects,
                'types/Pool/instances/getByName::{},{}'.format(
                    self.PROT_DOMAIN_ID,
                    self.STORAGE_POOL_NAME
                ): '"{}"'.format(self.STORAGE_POOL_ID),
                'instances/ProtectionDomain::{}'.format(
                    self.PROT_DOMAIN_ID
                ): {'id': self.PROT_DOMAIN_ID},
                'instances/StoragePool::{}'.format(
                    self.STORAGE_POOL_ID
                ): {'id': self.STORAGE_POOL_ID},
                'types/Domain/instances/getByName::' +
                self.PROT_DOMAIN_NAME: '"{}"'.format(self.PROT_DOMAIN_ID),
            },

        }

        with mock.patch('cinder.volume.volume_utils.'
                        'paginate_entries_list') as mpage:
            test_func = self.driver.get_manageable_volumes
            test_func(cinder_objs, marker, limit, offset, sort_keys, sort_dirs)
            mpage.assert_called_once_with(
                expected_refs,
                marker,
                limit,
                offset,
                sort_keys,
                sort_dirs
            )

    def test_get_manageable_volumes(self):
        """Default success case.

        Given a list of PowerFlex volumes from the REST API, give back a list
        of volume references.
        """

        self._test_get_manageable_things()

    def test_get_manageable_volumes_connected_vol(self):
        """Make sure volumes connected to hosts are flagged as unsafe."""
        mapped_sdc = deepcopy(MANAGEABLE_FLEX_VOLS)
        mapped_sdc[0]['mappedSdcInfo'] = ["host1"]
        mapped_sdc[1]['mappedSdcInfo'] = ["host1", "host2"]

        # change up the expected results
        expected_refs = deepcopy(MANAGEABLE_FLEX_VOL_REFS)
        for x in range(len(mapped_sdc)):
            sdc = mapped_sdc[x]['mappedSdcInfo']
            if sdc and len(sdc) > 0:
                expected_refs[x]['safe_to_manage'] = False
                expected_refs[x]['reason_not_safe'] \
                    = 'Volume mapped to %d host(s).' % len(sdc)

        self._test_get_manageable_things(expected_refs=expected_refs,
                                         powerflex_objects=mapped_sdc)

    def test_get_manageable_volumes_already_managed(self):
        """Make sure volumes already owned by cinder are flagged as unsafe."""
        cinder_vol = fake_volume.fake_volume_obj(mock.MagicMock())
        cinder_vol.id = VOLUME_ID
        cinder_vol.provider_id = PROVIDER_ID
        cinders_vols = [cinder_vol]

        # change up the expected results
        expected_refs = deepcopy(MANAGEABLE_FLEX_VOL_REFS)
        expected_refs[0]['reference'] = {'source-id': PROVIDER_ID}
        expected_refs[0]['safe_to_manage'] = False
        expected_refs[0]['reason_not_safe'] = 'Volume already managed.'
        expected_refs[0]['cinder_id'] = VOLUME_ID

        self._test_get_manageable_things(expected_refs=expected_refs,
                                         cinder_objs=cinders_vols)

    def test_get_manageable_volumes_no_snapshots(self):
        """Make sure refs returned do not include snapshots."""
        volumes = deepcopy(MANAGEABLE_FLEX_VOLS)
        volumes.append(POWERFLEX_SNAPSHOT)

        self._test_get_manageable_things(powerflex_objects=volumes)

    def test_get_manageable_volumes_no_powerflex_volumes(self):
        """Expect no refs to be found if no volumes are on PowerFlex."""
        self._test_get_manageable_things(powerflex_objects=[],
                                         expected_refs=[])
