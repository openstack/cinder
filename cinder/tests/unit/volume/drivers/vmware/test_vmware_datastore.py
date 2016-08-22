# Copyright (c) 2014 VMware, Inc.
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
Unit tests for datastore module.
"""

import mock
from oslo_utils import units

from cinder import test
from cinder.volume.drivers.vmware import datastore as ds_sel
from cinder.volume.drivers.vmware import exceptions as vmdk_exceptions


class DatastoreTest(test.TestCase):
    """Unit tests for Datastore."""

    def setUp(self):
        super(DatastoreTest, self).setUp()
        self._session = mock.Mock()
        self._vops = mock.Mock()
        self._ds_sel = ds_sel.DatastoreSelector(
            self._vops, self._session, 1024)

    @mock.patch('oslo_vmware.pbm.get_profile_id_by_name')
    def test_get_profile_id(self, get_profile_id_by_name):
        profile_id = mock.sentinel.profile_id
        get_profile_id_by_name.return_value = profile_id
        profile_name = mock.sentinel.profile_name

        self.assertEqual(profile_id, self._ds_sel.get_profile_id(profile_name))
        get_profile_id_by_name.assert_called_once_with(self._session,
                                                       profile_name)

    @mock.patch('oslo_vmware.pbm.get_profile_id_by_name')
    def test_get_profile_id_with_invalid_profile(self, get_profile_id_by_name):
        get_profile_id_by_name.return_value = None
        profile_name = mock.sentinel.profile_name

        self.assertRaises(vmdk_exceptions.ProfileNotFoundException,
                          self._ds_sel.get_profile_id,
                          profile_name)
        get_profile_id_by_name.assert_called_once_with(self._session,
                                                       profile_name)

    def _create_datastore(self, value):
        return mock.Mock(name=value, value=value)

    def _create_summary(
            self, ds, free_space=units.Mi, _type=ds_sel.DatastoreType.VMFS,
            capacity=2 * units.Mi, accessible=True):
        return mock.Mock(datastore=ds, freeSpace=free_space, type=_type,
                         capacity=capacity, accessible=accessible,
                         name=ds.value)

    def _create_host(self, value):
        host = mock.Mock(spec=['_type', 'value'], name=value)
        host._type = 'HostSystem'
        host.value = value
        return host

    @mock.patch('cinder.volume.drivers.vmware.datastore.DatastoreSelector.'
                '_filter_by_profile')
    def test_filter_datastores(self, filter_by_profile):
        host1 = self._create_host('host-1')
        host2 = self._create_host('host-2')
        host3 = self._create_host('host-3')

        host_mounts1 = [mock.Mock(key=host1)]
        host_mounts2 = [mock.Mock(key=host2)]
        host_mounts3 = [mock.Mock(key=host3)]

        # empty summary
        ds1 = self._create_datastore('ds-1')
        ds1_props = {'host': host_mounts1}

        # hard anti-affinity datastore
        ds2 = self._create_datastore('ds-2')
        ds2_props = {'summary': self._create_summary(ds2),
                     'host': host_mounts2}

        # not enough free space
        ds3 = self._create_datastore('ds-3')
        ds3_props = {'summary': self._create_summary(ds3, free_space=128),
                     'host': host_mounts1}

        # not connected to a valid host
        ds4 = self._create_datastore('ds-4')
        ds4_props = {'summary': self._create_summary(ds4),
                     'host': host_mounts3}

        # invalid datastore type
        ds5 = self._create_datastore('ds-5')
        ds5_props = {'summary': self._create_summary(ds5, _type='foo'),
                     'host': host_mounts1}

        # hard affinity datastore type
        ds6 = self._create_datastore('ds-6')
        ds6_props = {
            'summary': self._create_summary(
                ds6, _type=ds_sel.DatastoreType.VSAN),
            'host': host_mounts2}

        # inaccessible datastore
        ds7 = self._create_datastore('ds-7')
        ds7_props = {'summary': self._create_summary(ds7, accessible=False),
                     'host': host_mounts1}

        def mock_in_maintenace(summary):
            return summary.datastore.value == 'ds-8'

        self._vops._in_maintenance.side_effect = mock_in_maintenace
        # in-maintenance datastore
        ds8 = self._create_datastore('ds-8')
        ds8_props = {'summary': self._create_summary(ds8),
                     'host': host_mounts2}

        # not compliant with profile
        ds9 = self._create_datastore('ds-9')
        ds9_props = {'summary': self._create_summary(ds9),
                     'host': host_mounts1}

        # valid datastore
        ds10 = self._create_datastore('ds-10')
        ds10_props = {'summary': self._create_summary(ds10),
                      'host': host_mounts1}
        filter_by_profile.return_value = {ds10: ds10_props}

        datastores = {ds1: ds1_props,
                      ds2: ds2_props,
                      ds3: ds3_props,
                      ds4: ds4_props,
                      ds5: ds5_props,
                      ds6: ds6_props,
                      ds7: ds7_props,
                      ds8: ds8_props,
                      ds9: ds9_props,
                      ds10: ds10_props}
        profile_id = mock.sentinel.profile_id
        datastores = self._ds_sel._filter_datastores(
            datastores,
            512,
            profile_id,
            ['ds-2'],
            {ds_sel.DatastoreType.VMFS, ds_sel.DatastoreType.NFS},
            valid_host_refs=[host1, host2])

        self.assertEqual({ds10: ds10_props}, datastores)
        filter_by_profile.assert_called_once_with(
            {ds9: ds9_props, ds10: ds10_props},
            profile_id)

    def test_filter_datastores_with_empty_datastores(self):
        self.assertIsNone(self._ds_sel._filter_datastores(
            {}, 1024, None, None, None))

    def _create_host_properties(
            self, parent, connection_state='connected', in_maintenace=False):
        return mock.Mock(connectionState=connection_state,
                         inMaintenanceMode=in_maintenace,
                         parent=parent)

    @mock.patch('cinder.volume.drivers.vmware.datastore.DatastoreSelector.'
                '_get_host_properties')
    @mock.patch('cinder.volume.drivers.vmware.datastore.DatastoreSelector.'
                '_get_resource_pool')
    def test_select_best_datastore(self, get_resource_pool, get_host_props):
        host1 = self._create_host('host-1')
        host2 = self._create_host('host-2')
        host3 = self._create_host('host-3')

        host_mounts1 = [mock.Mock(key=host1,
                                  mountInfo=mock.sentinel.ds1_mount_info1),
                        mock.Mock(key=host2,
                                  mountInfo=mock.sentinel.ds1_mount_info2),
                        mock.Mock(key=host3,
                                  mountInfo=mock.sentinel.ds1_mount_info3)]
        host_mounts2 = [mock.Mock(key=host2,
                                  mountInfo=mock.sentinel.ds2_mount_info2),
                        mock.Mock(key=host3,
                                  mountInfo=mock.sentinel.ds2_mount_info3)]
        host_mounts3 = [mock.Mock(key=host1,
                                  mountInfo=mock.sentinel.ds3_mount_info1),
                        mock.Mock(key=host2,
                                  mountInfo=mock.sentinel.ds3_mount_info2)]
        host_mounts4 = [mock.Mock(key=host1,
                                  mountInfo=mock.sentinel.ds4_mount_info1)]

        ds1 = self._create_datastore('ds-1')
        ds1_props = {'summary': self._create_summary(ds1),
                     'host': host_mounts1}

        ds2 = self._create_datastore('ds-2')
        ds2_props = {
            'summary': self._create_summary(
                ds2, free_space=1024, capacity=2048),
            'host': host_mounts2}

        ds3 = self._create_datastore('ds-3')
        ds3_props = {
            'summary': self._create_summary(
                ds3, free_space=512, capacity=2048),
            'host': host_mounts3}

        ds4 = self._create_datastore('ds-3')
        ds4_props = {'summary': self._create_summary(ds4),
                     'host': host_mounts4}

        cluster_ref = mock.sentinel.cluster_ref

        def mock_get_host_properties(host_ref):
            self.assertIsNot(host1, host_ref)
            if host_ref == host2:
                in_maintenance = False
            else:
                in_maintenance = True
            runtime = mock.Mock(spec=['connectionState', 'inMaintenanceMode'])
            runtime.connectionState = 'connected'
            runtime.inMaintenanceMode = in_maintenance
            return {'parent': cluster_ref, 'runtime': runtime}

        get_host_props.side_effect = mock_get_host_properties

        def mock_is_usable(mount_info):
            if (mount_info == mock.sentinel.ds1_mount_info2 or
                    mount_info == mock.sentinel.ds2_mount_info2):
                return False
            else:
                return True

        self._vops._is_usable.side_effect = mock_is_usable

        rp = mock.sentinel.resource_pool
        get_resource_pool.return_value = rp

        # ds1 is mounted to 3 hosts: host1, host2 and host3; host1 is
        # not a valid host, ds1 is not usable in host1, and host3 is
        # in maintenance mode.
        # ds2 and ds3 are mounted to same hosts, and ds2 has a low space
        # utilization. But ds2 is not usable in host2, and host3 is in
        # maintenance mode. Therefore, ds3 and host2 will be selected.
        datastores = {ds1: ds1_props,
                      ds2: ds2_props,
                      ds3: ds3_props,
                      ds4: ds4_props}
        ret = self._ds_sel._select_best_datastore(
            datastores, valid_host_refs=[host2, host3])

        self.assertEqual((host2, rp, ds3_props['summary']), ret)
        self.assertItemsEqual([mock.call(mock.sentinel.ds1_mount_info2),
                               mock.call(mock.sentinel.ds1_mount_info3),
                               mock.call(mock.sentinel.ds2_mount_info2),
                               mock.call(mock.sentinel.ds2_mount_info3),
                               mock.call(mock.sentinel.ds3_mount_info2)],
                              self._vops._is_usable.call_args_list)
        self.assertEqual([mock.call(host3), mock.call(host2)],
                         get_host_props.call_args_list)
        get_resource_pool.assert_called_once_with(cluster_ref)

    def test_select_best_datastore_with_empty_datastores(self):
        self.assertIsNone(self._ds_sel._select_best_datastore({}))

    @mock.patch('cinder.volume.drivers.vmware.datastore.DatastoreSelector.'
                'get_profile_id')
    @mock.patch('cinder.volume.drivers.vmware.datastore.DatastoreSelector.'
                '_get_datastores')
    @mock.patch('cinder.volume.drivers.vmware.datastore.DatastoreSelector.'
                '_filter_datastores')
    @mock.patch('cinder.volume.drivers.vmware.datastore.DatastoreSelector.'
                '_select_best_datastore')
    def test_select_datastore(
            self, select_best_datastore, filter_datastores, get_datastores,
            get_profile_id):

        profile_id = mock.sentinel.profile_id
        get_profile_id.return_value = profile_id

        datastores = mock.sentinel.datastores
        get_datastores.return_value = datastores

        filtered_datastores = mock.sentinel.filtered_datastores
        filter_datastores.return_value = filtered_datastores

        best_datastore = mock.sentinel.best_datastore
        select_best_datastore.return_value = best_datastore

        size_bytes = 1024
        req = {self._ds_sel.SIZE_BYTES: size_bytes}
        aff_ds_types = [ds_sel.DatastoreType.VMFS]
        req[ds_sel.DatastoreSelector.HARD_AFFINITY_DS_TYPE] = aff_ds_types
        anti_affinity_ds = [mock.sentinel.ds]
        req[ds_sel.DatastoreSelector.HARD_ANTI_AFFINITY_DS] = anti_affinity_ds
        profile_name = mock.sentinel.profile_name
        req[ds_sel.DatastoreSelector.PROFILE_NAME] = profile_name

        hosts = mock.sentinel.hosts
        self.assertEqual(best_datastore,
                         self._ds_sel.select_datastore(req, hosts))
        get_datastores.assert_called_once_with()
        filter_datastores.assert_called_once_with(
            datastores, size_bytes, profile_id, anti_affinity_ds, aff_ds_types,
            valid_host_refs=hosts)
        select_best_datastore.assert_called_once_with(filtered_datastores,
                                                      valid_host_refs=hosts)

    @mock.patch('oslo_vmware.pbm.get_profile_id_by_name')
    @mock.patch('cinder.volume.drivers.vmware.datastore.DatastoreSelector.'
                '_filter_by_profile')
    def test_is_datastore_compliant(self, filter_by_profile,
                                    get_profile_id_by_name):
        # Test with empty profile.
        profile_name = None
        datastore = mock.sentinel.datastore
        self.assertTrue(self._ds_sel.is_datastore_compliant(datastore,
                                                            profile_name))

        # Test with invalid profile.
        profile_name = mock.sentinel.profile_name
        get_profile_id_by_name.return_value = None
        self.assertRaises(vmdk_exceptions.ProfileNotFoundException,
                          self._ds_sel.is_datastore_compliant,
                          datastore,
                          profile_name)
        get_profile_id_by_name.assert_called_once_with(self._session,
                                                       profile_name)

        # Test with valid profile and non-compliant datastore.
        get_profile_id_by_name.reset_mock()
        profile_id = mock.sentinel.profile_id
        get_profile_id_by_name.return_value = profile_id
        filter_by_profile.return_value = {}
        self.assertFalse(self._ds_sel.is_datastore_compliant(datastore,
                                                             profile_name))
        get_profile_id_by_name.assert_called_once_with(self._session,
                                                       profile_name)
        filter_by_profile.assert_called_once_with({datastore: None},
                                                  profile_id)

        # Test with valid profile and compliant datastore.
        get_profile_id_by_name.reset_mock()
        filter_by_profile.reset_mock()
        filter_by_profile.return_value = {datastore: None}
        self.assertTrue(self._ds_sel.is_datastore_compliant(datastore,
                                                            profile_name))
        get_profile_id_by_name.assert_called_once_with(self._session,
                                                       profile_name)
        filter_by_profile.assert_called_once_with({datastore: None},
                                                  profile_id)
