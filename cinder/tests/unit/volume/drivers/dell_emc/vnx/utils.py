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


from os import path

import mock
import six
import yaml

from cinder.volume.drivers.dell_emc.vnx import client
from cinder.volume.drivers.dell_emc.vnx import common


patch_sleep = mock.patch('time.sleep')


patch_vnxsystem = mock.patch('storops.VNXSystem')


patch_vnxstoragegroup = mock.patch('storops.vnx.resource.sg.VNXStorageGroup')


def load_yaml(file_name):
    yaml_file = '{}/{}'.format(path.dirname(
        path.abspath(__file__)), file_name)
    with open(yaml_file) as f:
        res = yaml.safe_load(f)
    return res


def patch_extra_specs(specs):
    return _build_patch_decorator(
        'cinder.volume.volume_types.get_volume_type_extra_specs',
        return_value=specs)


def patch_group_specs(specs):
    return _build_patch_decorator(
        'cinder.volume.group_types.get_group_type_specs',
        return_value=specs)


def patch_extra_specs_validate(return_value=None, side_effect=None):
    return _build_patch_decorator(
        'cinder.volume.drivers.dell_emc.vnx.common.ExtraSpecs.validate',
        return_value=return_value,
        side_effect=side_effect)


def _build_patch_decorator(module_str, return_value=None, side_effect=None):
    def _inner_mock(func):
        @six.wraps(func)
        def decorator(*args, **kwargs):
            with mock.patch(
                    module_str,
                    return_value=return_value,
                    side_effect=side_effect):
                return func(*args, **kwargs)
        return decorator
    return _inner_mock


def build_fake_mirror_view():
    primary_client = mock.create_autospec(spec=client.Client)
    secondary_client = mock.create_autospec(spec=client.Client)

    mirror_view = mock.create_autospec(spec=common.VNXMirrorView)
    mirror_view.primary_client = primary_client
    mirror_view.secondary_client = secondary_client
    return mirror_view


def get_replication_device():
    return {
        'backend_id': 'fake_serial',
        'san_ip': '192.168.1.12',
        'san_login': 'admin',
        'san_password': 'admin',
        'storage_vnx_authentication_type': 'global',
        'storage_vnx_security_file_dir': None,
        'pool_name': 'remote_pool',
    }
