# Copyright (c) 2013 - 2015 EMC Corporation.
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
import json
import requests
import six

from cinder.volume import configuration as conf
from cinder.volume.drivers.emc import scaleio
from oslo_config import cfg


class ScaleIODriver(scaleio.ScaleIODriver):
    """Mock ScaleIO Driver class.

    Provides some fake configuration options
    """
    def __init__(self, *args, **kwargs):
        configuration = conf.Configuration(
            [
                cfg.StrOpt('fake'),
            ],
            None
        )

        # Override the defaults to fake values
        configuration.set_override('san_ip', override='127.0.0.1')
        configuration.set_override('sio_rest_server_port', override='8888')
        configuration.set_override('san_login', override='test')
        configuration.set_override('san_password', override='pass')
        configuration.set_override('sio_storage_pool_id', override='test_pool')
        configuration.set_override('sio_protection_domain_id',
                                   override='test_domain')
        configuration.set_override('sio_storage_pools',
                                   override='test_domain:test_pool')

        super(ScaleIODriver, self).__init__(configuration=configuration,
                                            *args,
                                            **kwargs)

    def update_consistencygroup(self, context, group, add_volumes=None,
                                remove_volumes=None):
        pass

    def local_path(self, volume):
        pass

    def reenable_replication(self, context, volume):
        pass

    def manage_existing(self, volume, existing_ref):
        pass

    def promote_replica(self, context, volume):
        pass

    def delete_consistencygroup(self, context, group):
        pass

    def create_consistencygroup_from_src(self, context, group, volumes,
                                         cgsnapshot=None, snapshots=None):
        pass

    def create_replica_test_volume(self, volume, src_vref):
        pass

    def create_consistencygroup(self, context, group):
        pass

    def manage_existing_get_size(self, volume, existing_ref):
        pass

    def unmanage(self, volume):
        pass

    def create_cgsnapshot(self, context, cgsnapshot):
        pass

    def delete_cgsnapshot(self, context, cgsnapshot):
        pass


class MockHTTPSResponse(requests.Response):
    """Mock HTTP Response

    Defines the https replies from the mocked calls to do_request()
    """
    def __init__(self, content, status_code=200):
        super(MockHTTPSResponse, self).__init__()

        if isinstance(content, six.text_type):
            content = content.encode('utf-8')
        self._content = content
        self.status_code = status_code

    def json(self, **kwargs):
        if isinstance(self._content, (bytes, six.text_type)):
            return super(MockHTTPSResponse, self).json(**kwargs)

        return self._content

    @property
    def text(self):
        if not isinstance(self._content, (bytes, six.text_type)):
            return json.dumps(self._content)

        return super(MockHTTPSResponse, self).text
