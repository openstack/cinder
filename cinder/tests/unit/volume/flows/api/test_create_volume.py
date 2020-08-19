# Copyright 2020 Red Hat Inc.
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
""" Tests for create_volume in the TaskFlow volume.flow.api"""

from unittest import mock

import ddt

from cinder import context
from cinder import exception
from cinder.tests.unit import test
from cinder.volume.flows.api import create_volume
from cinder.volume import volume_types


@ddt.ddt
class ExtractVolumeRequestTaskValidationsTestCase(test.TestCase):
    """Test validation code.

    The ExtractVolumeRequestTask takes a set of inputs that will form a
    volume-create request and validates them, inferring values for "missing"
    inputs.

    This class tests the validation code, not the Task itself.
    """

    def setUp(self):
        super(ExtractVolumeRequestTaskValidationsTestCase, self).setUp()
        self.context = context.get_admin_context()

    fake_vol_type = 'vt-from-volume_type'
    fake_source_vol = {'volume_type_id': 'vt-from-source_vol'}
    fake_snapshot = {'volume_type_id': 'vt-from-snapshot'}
    fake_img_vol_type_id = 'vt-from-image_volume_type_id'
    fake_config_value = 'vt-from-config-value'

    big_ass_data_tuple = (
        # case 0: null params and no configured default should
        # result in the system default volume type
        {'param_vol_type': None,
         'param_source_vol': None,
         'param_snap': None,
         'param_img_vol_type_id': None,
         'config_value': volume_types.DEFAULT_VOLUME_TYPE,
         'expected_vol_type': volume_types.DEFAULT_VOLUME_TYPE},
        # case set 1: if a volume_type is passed, should always be selected
        {'param_vol_type': fake_vol_type,
         'param_source_vol': None,
         'param_snap': None,
         'param_img_vol_type_id': None,
         'config_value': volume_types.DEFAULT_VOLUME_TYPE,
         'expected_vol_type': 'vt-from-volume_type'},
        {'param_vol_type': fake_vol_type,
         'param_source_vol': fake_source_vol,
         'param_snap': fake_snapshot,
         'param_img_vol_type_id': fake_img_vol_type_id,
         'config_value': fake_config_value,
         'expected_vol_type': 'vt-from-volume_type'},
        # case set 2: if no volume_type is passed, the vt from the
        # source_volume should be selected
        {'param_vol_type': None,
         'param_source_vol': fake_source_vol,
         'param_snap': None,
         'param_img_vol_type_id': None,
         'config_value': volume_types.DEFAULT_VOLUME_TYPE,
         'expected_vol_type': 'vt-from-source_vol'},
        {'param_vol_type': None,
         'param_source_vol': fake_source_vol,
         'param_snap': fake_snapshot,
         'param_img_vol_type_id': fake_img_vol_type_id,
         'config_value': fake_config_value,
         'expected_vol_type': 'vt-from-source_vol'},
        # case set 3: no volume_type, no source_volume, so snapshot's type
        # should be selected
        {'param_vol_type': None,
         'param_source_vol': None,
         'param_snap': fake_snapshot,
         'param_img_vol_type_id': None,
         'config_value': volume_types.DEFAULT_VOLUME_TYPE,
         'expected_vol_type': 'vt-from-snapshot'},
        {'param_vol_type': None,
         'param_source_vol': None,
         'param_snap': fake_snapshot,
         'param_img_vol_type_id': fake_img_vol_type_id,
         'config_value': fake_config_value,
         'expected_vol_type': 'vt-from-snapshot'},
        # case set 4: no volume_type, no source_volume, no snapshot --
        # use the volume_type from the image metadata
        {'param_vol_type': None,
         'param_source_vol': None,
         'param_snap': None,
         'param_img_vol_type_id': fake_img_vol_type_id,
         'config_value': volume_types.DEFAULT_VOLUME_TYPE,
         'expected_vol_type': 'vt-from-image_volume_type_id'},
        {'param_vol_type': None,
         'param_source_vol': None,
         'param_snap': None,
         'param_img_vol_type_id': fake_img_vol_type_id,
         'config_value': fake_config_value,
         'expected_vol_type': 'vt-from-image_volume_type_id'},
        # case 5: params all null, should use configured volume_type
        {'param_vol_type': None,
         'param_source_vol': None,
         'param_snap': None,
         'param_img_vol_type_id': None,
         'config_value': fake_config_value,
         'expected_vol_type': 'vt-from-config-value'})

    def reflect_second(a, b):
        return b

    @ddt.data(*big_ass_data_tuple)
    @mock.patch('cinder.objects.VolumeType.get_by_name_or_id',
                side_effect = reflect_second)
    @mock.patch('cinder.volume.volume_types.get_volume_type_by_name',
                side_effect = reflect_second)
    @ddt.unpack
    def test__get_volume_type(self,
                              mock_get_volume_type_by_name,
                              mock_get_by_name_or_id,
                              param_vol_type,
                              param_source_vol,
                              param_snap,
                              param_img_vol_type_id,
                              config_value,
                              expected_vol_type):

        self.flags(default_volume_type=config_value)

        test_fn = create_volume.ExtractVolumeRequestTask._get_volume_type

        self.assertEqual(expected_vol_type,
                         test_fn(self.context,
                                 param_vol_type,
                                 param_source_vol,
                                 param_snap,
                                 param_img_vol_type_id))

    # Before the Train release, an invalid volume type specifier
    # would not raise an exception; it would log an error and you'd
    # get a volume with volume_type == None.  We want to verify that
    # specifying a non-existent volume_type always raises an exception
    smaller_data_tuple = (
        {'param_source_vol': fake_source_vol,
         'param_snap': None,
         'param_img_vol_type_id': None,
         'config_value': None},
        {'param_source_vol': None,
         'param_snap': fake_snapshot,
         'param_img_vol_type_id': None,
         'config_value': None},
        {'param_source_vol': None,
         'param_snap': None,
         'param_img_vol_type_id': fake_img_vol_type_id,
         'config_value': None},
        {'param_source_vol': None,
         'param_snap': None,
         'param_img_vol_type_id': None,
         'config_value': fake_config_value})

    @ddt.data(*smaller_data_tuple)
    @mock.patch('cinder.objects.VolumeType.get_by_name_or_id',
                side_effect = exception.VolumeTypeNotFoundByName(
                    volume_type_name="get_by_name_or_id"))
    @mock.patch('cinder.volume.volume_types.get_volume_type_by_name',
                side_effect = exception.VolumeTypeNotFoundByName(
                    volume_type_name="get_by_name"))
    @ddt.unpack
    def test_neg_get_volume_type(self,
                                 mock_get_volume_type_by_name,
                                 mock_get_by_name_or_id,
                                 param_source_vol,
                                 param_snap,
                                 param_img_vol_type_id,
                                 config_value):

        self.flags(default_volume_type=config_value)

        test_fn = create_volume.ExtractVolumeRequestTask._get_volume_type

        if config_value:
            self.assertRaises(exception.VolumeTypeDefaultMisconfiguredError,
                              test_fn,
                              self.context,
                              None,
                              param_source_vol,
                              param_snap,
                              param_img_vol_type_id)
        else:
            self.assertRaises(exception.VolumeTypeNotFoundByName,
                              test_fn,
                              self.context,
                              None,
                              param_source_vol,
                              param_snap,
                              param_img_vol_type_id)
