# Copyright (c) 2015 Hitachi Data Systems, Inc.
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

from cinder.api import common


class ViewBuilder(common.ViewBuilder):
    """Model capabilities API responses as a python dictionary."""

    _collection_name = "capabilities"

    def __init__(self):
        """Initialize view builder."""
        super(ViewBuilder, self).__init__()

    def summary(self, request, capabilities, id):
        """Summary view of a backend capabilities."""
        return {
            'namespace': 'OS::Storage::Capabilities::%s' % id,
            'vendor_name': capabilities.get('vendor_name'),
            'volume_backend_name': capabilities.get('volume_backend_name'),
            'pool_name': capabilities.get('pool_name'),
            'driver_version': capabilities.get('driver_version'),
            'storage_protocol': capabilities.get('storage_protocol'),
            'display_name': capabilities.get('display_name'),
            'description': capabilities.get('description'),
            'visibility': capabilities.get('visibility'),
            'properties': capabilities.get('properties'),
        }
