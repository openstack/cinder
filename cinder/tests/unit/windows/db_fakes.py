#  Copyright 2012 Pedro Navarro Perez
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
Stubouts, mocks and fixtures for windows volume test suite
"""


def get_fake_volume_info():
    return {'name': 'volume_name',
            'size': 1,
            'provider_location': 'iqn.2010-10.org.openstack:' + 'volume_name',
            'id': 1,
            'provider_auth': None}


def get_fake_volume_info_cloned():
    return {'name': 'volume_name_cloned',
            'size': 1,
            'provider_location': 'iqn.2010-10.org.openstack:' +
                                 'volume_name_cloned',
            'id': 1,
            'provider_auth': None}


def get_fake_image_meta():
    return {'id': '10958016-e196-42e3-9e7f-5d8927ae3099'
            }


def get_fake_snapshot_info():
    return {'name': 'snapshot_name',
            'volume_name': 'volume_name', }


def get_fake_connector_info():
    return {'initiator': 'iqn.2010-10.org.openstack:' + 'volume_name', }
