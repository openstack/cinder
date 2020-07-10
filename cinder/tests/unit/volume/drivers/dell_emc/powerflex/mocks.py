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

from oslo_config import cfg
import requests
import six

from cinder.volume.drivers.dell_emc.powerflex import driver
from cinder.volume.drivers.dell_emc.powerflex import rest_client

CONF = cfg.CONF


class PowerFlexDriver(driver.PowerFlexDriver):
    """Mock PowerFlex Driver class.

    Provides some fake configuration options
    """
    def do_setup(self, context):
        self.provisioning_type = (
            "thin" if self.configuration.san_thin_provision else "thick"
        )
        self.configuration.max_over_subscription_ratio = (
            self.configuration.powerflex_max_over_subscription_ratio
        )

    def local_path(self, volume):
        pass

    def reenable_replication(self, context, volume):
        pass

    def promote_replica(self, context, volume):
        pass

    def unmanage(self, volume):
        pass


class PowerFlexClient(rest_client.RestClient):
    """Mock PowerFlex Rest Client class.

    Provides some fake configuration options
    """

    def is_volume_creation_safe(self, _pd, _sp):
        return True


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
