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

from cinder.openstack.common import units
from cinder import test
from cinder.volume.drivers.vmware import datastore as ds_sel
from cinder.volume.drivers.vmware import error_util


class DatastoreTest(test.TestCase):
    """Unit tests for Datastore."""

    def setUp(self):
        super(DatastoreTest, self).setUp()
        self._session = mock.Mock()
        self._vops = mock.Mock()
        self._ds_sel = ds_sel.DatastoreSelector(self._vops, self._session)

    def test_get_profile_id(self):
        profile_id = mock.sentinel.profile_id
        self._vops.retrieve_profile_id.return_value = profile_id
        profile_name = mock.sentinel.profile_name

        self.assertEqual(profile_id, self._ds_sel.get_profile_id(profile_name))
        self._vops.retrieve_profile_id.assert_called_once_with(profile_name)

    def test_get_profile_id_with_invalid_profile(self):
        self._vops.retrieve_profile_id.return_value = None
        profile_name = mock.sentinel.profile_name

        self.assertRaises(error_util.ProfileNotFoundException,
                          self._ds_sel.get_profile_id,
                          profile_name)
        self._vops.retrieve_profile_id.assert_called_once_with(profile_name)

    def _create_datastore(self, moref):
        return mock.Mock(value=moref)

    def _create_summary(
            self, ds, free_space=units.Mi, _type=ds_sel.DatastoreType.VMFS,
            capacity=2 * units.Mi):
        return mock.Mock(datastore=ds, freeSpace=free_space, type=_type,
                         capacity=capacity)

    @mock.patch('cinder.volume.drivers.vmware.datastore.DatastoreSelector.'
                '_filter_by_profile')
    def test_filter_datastores(self, filter_by_profile):
        # Test with empty datastore list.
        datastores = []
        size_bytes = 2 * units.Mi
        profile_id = mock.sentinel.profile_id
        hard_anti_affinity_datastores = None
        hard_affinity_ds_types = None

        self.assertEqual([], self._ds_sel._filter_datastores(
            datastores, size_bytes, profile_id, hard_anti_affinity_datastores,
            hard_affinity_ds_types))

        # Test with single datastore with hard anti-affinity.
        ds_1 = self._create_datastore('ds-1')
        datastores = [ds_1]
        hard_anti_affinity_datastores = [ds_1.value]

        self.assertEqual([], self._ds_sel._filter_datastores(
            datastores, size_bytes, profile_id, hard_anti_affinity_datastores,
            hard_affinity_ds_types))

        # Extend previous case with a profile non-compliant datastore.
        ds_2 = self._create_datastore('ds-2')
        datastores.append(ds_2)
        filter_by_profile.return_value = []

        self.assertEqual([], self._ds_sel._filter_datastores(
            datastores, size_bytes, profile_id, hard_anti_affinity_datastores,
            hard_affinity_ds_types))
        filter_by_profile.assert_called_once_with([ds_2], profile_id)

        # Extend previous case with a less free space datastore.
        ds_3 = self._create_datastore('ds-3')
        datastores.append(ds_3)
        filter_by_profile.return_value = [ds_3]

        free_space_list = [units.Mi]
        type_list = [ds_sel.DatastoreType.NFS]
        self._vops.get_summary.side_effect = (
            lambda ds: self._create_summary(ds,
                                            free_space_list.pop(0),
                                            type_list.pop(0)))

        self.assertEqual([], self._ds_sel._filter_datastores(
            datastores, size_bytes, profile_id, hard_anti_affinity_datastores,
            hard_affinity_ds_types))

        # Extend previous case with a datastore not satisfying hard affinity
        # datastore type requirement.
        ds_4 = self._create_datastore('ds-4')
        datastores.append(ds_4)
        filter_by_profile.return_value = [ds_3, ds_4]

        free_space_list = [units.Mi, 4 * units.Mi]
        type_list = [ds_sel.DatastoreType.NFS, ds_sel.DatastoreType.VSAN]
        hard_affinity_ds_types = [ds_sel.DatastoreType.NFS]

        self.assertEqual([], self._ds_sel._filter_datastores(
            datastores, size_bytes, profile_id, hard_anti_affinity_datastores,
            hard_affinity_ds_types))

        # Modify the previous case to remove hard affinity datastore type
        # requirement.
        free_space_list = [units.Mi, 4 * units.Mi]
        type_list = [ds_sel.DatastoreType.NFS, ds_sel.DatastoreType.VSAN]
        hard_affinity_ds_types = None

        res = self._ds_sel._filter_datastores(
            datastores, size_bytes, profile_id, hard_anti_affinity_datastores,
            hard_affinity_ds_types)
        self.assertTrue(len(res) == 1)
        self.assertEqual(ds_4, res[0].datastore)

        # Extend the previous case by adding a datastore satisfying
        # hard affinity datastore type requirement.
        ds_5 = self._create_datastore('ds-5')
        datastores.append(ds_5)
        filter_by_profile.return_value = [ds_3, ds_4, ds_5]

        free_space_list = [units.Mi, 4 * units.Mi, 5 * units.Mi]
        type_list = [ds_sel.DatastoreType.NFS, ds_sel.DatastoreType.VSAN,
                     ds_sel.DatastoreType.VMFS]
        hard_affinity_ds_types = [ds_sel.DatastoreType.VMFS]

        res = self._ds_sel._filter_datastores(
            datastores, size_bytes, profile_id, hard_anti_affinity_datastores,
            hard_affinity_ds_types)
        self.assertTrue(len(res) == 1)
        self.assertEqual(ds_5, res[0].datastore)

        # Modify the previous case to have two datastores satisfying
        # hard affinity datastore type requirement.
        free_space_list = [units.Mi, 4 * units.Mi, 5 * units.Mi]
        type_list = [ds_sel.DatastoreType.NFS, ds_sel.DatastoreType.VSAN,
                     ds_sel.DatastoreType.VSAN]
        hard_affinity_ds_types = [ds_sel.DatastoreType.VSAN]

        res = self._ds_sel._filter_datastores(
            datastores, size_bytes, profile_id, hard_anti_affinity_datastores,
            hard_affinity_ds_types)
        self.assertTrue(len(res) == 2)
        self.assertEqual(ds_4, res[0].datastore)
        self.assertEqual(ds_5, res[1].datastore)

        # Clear side effects.
        self._vops.get_summary.side_effect = None

    def test_select_best_summary(self):
        # No tie-- all datastores with different host mount count.
        summary_1 = self._create_summary(mock.sentinel.ds_1,
                                         free_space=units.Mi,
                                         capacity=2 * units.Mi)
        summary_2 = self._create_summary(mock.sentinel.ds_2,
                                         free_space=units.Mi,
                                         capacity=3 * units.Mi)
        summary_3 = self._create_summary(mock.sentinel.ds_3,
                                         free_space=units.Mi,
                                         capacity=4 * units.Mi)

        host_1 = mock.sentinel.host_1
        host_2 = mock.sentinel.host_3
        host_3 = mock.sentinel.host_3

        connected_hosts = {mock.sentinel.ds_1: [host_1],
                           mock.sentinel.ds_2: [host_1, host_2],
                           mock.sentinel.ds_3: [host_1, host_2, host_3]}
        self._vops.get_connected_hosts.side_effect = (
            lambda summary: connected_hosts[summary])

        summaries = [summary_1, summary_2, summary_3]
        (best_summary, best_utilization) = self._ds_sel._select_best_summary(
            summaries)

        self.assertEqual(summary_3, best_summary)
        self.assertEqual(3 / 4.0, best_utilization)

        # Tie-- two datastores with max host mount count.
        summary_4 = self._create_summary(mock.sentinel.ds_4,
                                         free_space=2 * units.Mi,
                                         capacity=4 * units.Mi)
        connected_hosts[mock.sentinel.ds_4] = (
            connected_hosts[mock.sentinel.ds_3])
        summaries.append(summary_4)
        (best_summary, best_utilization) = self._ds_sel._select_best_summary(
            summaries)

        self.assertEqual(summary_4, best_summary)
        self.assertEqual(1 / 2.0, best_utilization)

        # Clear side effects.
        self._vops.get_connected_hosts.side_effect = None

    @mock.patch('cinder.volume.drivers.vmware.datastore.DatastoreSelector.'
                'get_profile_id')
    @mock.patch('cinder.volume.drivers.vmware.datastore.DatastoreSelector.'
                '_filter_datastores')
    def test_select_datastore(self, filter_datastores, get_profile_id):
        # Test with no hosts.
        size_bytes = units.Ki
        req = {self._ds_sel.SIZE_BYTES: size_bytes}
        self._vops.get_hosts.return_value = mock.Mock(objects=[])

        self.assertEqual((), self._ds_sel.select_datastore(req))
        self._vops.get_hosts.assert_called_once_with()

        # Test with single host with no valid datastores.
        host_1 = mock.sentinel.host_1
        self._vops.get_hosts.return_value = mock.Mock(
            objects=[mock.Mock(obj=host_1)])
        self._vops.continue_retrieval.return_value = None
        self._vops.get_dss_rp.side_effect = error_util.VimException('error')

        self.assertEqual((), self._ds_sel.select_datastore(req))
        self._vops.get_dss_rp.assert_called_once_with(host_1)

        # Test with three hosts and vCenter connection problem while fetching
        # datastores for the second host.
        self._vops.get_dss_rp.reset_mock()
        host_2 = mock.sentinel.host_2
        host_3 = mock.sentinel.host_3
        self._vops.get_hosts.return_value = mock.Mock(
            objects=[mock.Mock(obj=host_1),
                     mock.Mock(obj=host_2),
                     mock.Mock(obj=host_3)])
        self._vops.get_dss_rp.side_effect = [
            error_util.VimException('no valid datastores'),
            error_util.VimConnectionException('connection error')]

        self.assertRaises(error_util.VimConnectionException,
                          self._ds_sel.select_datastore,
                          req)
        get_dss_rp_exp_calls = [mock.call(host_1), mock.call(host_2)]
        self.assertEqual(get_dss_rp_exp_calls,
                         self._vops.get_dss_rp.call_args_list)

        # Modify previous case to return datastores for second and third host,
        # where none of them meet the requirements which include a storage
        # profile and affinity requirements.
        aff_ds_types = [ds_sel.DatastoreType.VMFS]
        req[ds_sel.DatastoreSelector.HARD_AFFINITY_DS_TYPE] = aff_ds_types

        ds_1a = mock.sentinel.ds_1a
        anti_affinity_ds = [ds_1a]
        req[ds_sel.DatastoreSelector.HARD_ANTI_AFFINITY_DS] = anti_affinity_ds

        profile_name = mock.sentinel.profile_name
        req[ds_sel.DatastoreSelector.PROFILE_NAME] = profile_name

        profile_id = mock.sentinel.profile_id
        get_profile_id.return_value = profile_id

        ds_2a = mock.sentinel.ds_2a
        ds_2b = mock.sentinel.ds_2b
        ds_3a = mock.sentinel.ds_3a

        self._vops.get_dss_rp.reset_mock()
        rp_2 = mock.sentinel.rp_2
        rp_3 = mock.sentinel.rp_3
        self._vops.get_dss_rp.side_effect = [
            error_util.VimException('no valid datastores'),
            ([ds_2a, ds_2b], rp_2),
            ([ds_3a], rp_3)]

        filter_datastores.return_value = []

        self.assertEqual((), self._ds_sel.select_datastore(req))
        get_profile_id.assert_called_once_with(profile_name)
        get_dss_rp_exp_calls.append(mock.call(host_3))
        self.assertEqual(get_dss_rp_exp_calls,
                         self._vops.get_dss_rp.call_args_list)
        filter_datastores_exp_calls = [
            mock.call([ds_2a, ds_2b], size_bytes, profile_id, anti_affinity_ds,
                      aff_ds_types),
            mock.call([ds_3a], size_bytes, profile_id, anti_affinity_ds,
                      aff_ds_types)]
        self.assertEqual(filter_datastores_exp_calls,
                         filter_datastores.call_args_list)

        # Modify previous case to have a non-empty summary list after filtering
        # with preferred utilization threshold unset.
        self._vops.get_dss_rp.side_effect = [
            error_util.VimException('no valid datastores'),
            ([ds_2a, ds_2b], rp_2),
            ([ds_3a], rp_3)]

        summary_2b = self._create_summary(ds_2b, free_space=0.5 * units.Mi,
                                          capacity=units.Mi)
        filter_datastores.side_effect = [[summary_2b]]
        self._vops.get_connected_hosts.return_value = [host_1]

        self.assertEqual((host_2, rp_2, summary_2b),
                         self._ds_sel.select_datastore(req))

        # Modify previous case to have a preferred utilization threshold
        # satsified by one datastore.
        self._vops.get_dss_rp.side_effect = [
            error_util.VimException('no valid datastores'),
            ([ds_2a, ds_2b], rp_2),
            ([ds_3a], rp_3)]

        req[ds_sel.DatastoreSelector.PREF_UTIL_THRESH] = 0.4
        summary_3a = self._create_summary(ds_3a, free_space=0.7 * units.Mi,
                                          capacity=units.Mi)
        filter_datastores.side_effect = [[summary_2b], [summary_3a]]

        self.assertEqual((host_3, rp_3, summary_3a),
                         self._ds_sel.select_datastore(req))

        # Modify previous case to have a preferred utilization threshold
        # which cannot be satisfied.
        self._vops.get_dss_rp.side_effect = [
            error_util.VimException('no valid datastores'),
            ([ds_2a, ds_2b], rp_2),
            ([ds_3a], rp_3)]
        filter_datastores.side_effect = [[summary_2b], [summary_3a]]

        req[ds_sel.DatastoreSelector.PREF_UTIL_THRESH] = 0.2
        summary_2b.freeSpace = 0.75 * units.Mi

        self.assertEqual((host_2, rp_2, summary_2b),
                         self._ds_sel.select_datastore(req))

        # Clear side effects.
        self._vops.get_dss_rp.side_effect = None

    @mock.patch('cinder.volume.drivers.vmware.datastore.DatastoreSelector.'
                '_filter_by_profile')
    def test_is_datastore_compliant(self, filter_by_profile):
        # Test with empty profile.
        profile_name = None
        datastore = mock.sentinel.datastore
        self.assertTrue(self._ds_sel.is_datastore_compliant(datastore,
                                                            profile_name))

        # Test with invalid profile.
        profile_name = mock.sentinel.profile_name
        self._vops.retrieve_profile_id.return_value = None
        self.assertRaises(error_util.ProfileNotFoundException,
                          self._ds_sel.is_datastore_compliant,
                          datastore,
                          profile_name)
        self._vops.retrieve_profile_id.assert_called_once_with(profile_name)

        # Test with valid profile and non-compliant datastore.
        self._vops.retrieve_profile_id.reset_mock()
        profile_id = mock.sentinel.profile_id
        self._vops.retrieve_profile_id.return_value = profile_id
        filter_by_profile.return_value = []
        self.assertFalse(self._ds_sel.is_datastore_compliant(datastore,
                                                             profile_name))
        self._vops.retrieve_profile_id.assert_called_once_with(profile_name)
        filter_by_profile.assert_called_once_with([datastore], profile_id)

        # Test with valid profile and compliant datastore.
        self._vops.retrieve_profile_id.reset_mock()
        filter_by_profile.reset_mock()
        filter_by_profile.return_value = [datastore]
        self.assertTrue(self._ds_sel.is_datastore_compliant(datastore,
                                                            profile_name))
        self._vops.retrieve_profile_id.assert_called_once_with(profile_name)
        filter_by_profile.assert_called_once_with([datastore], profile_id)
