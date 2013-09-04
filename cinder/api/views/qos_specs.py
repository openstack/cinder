# Copyright (C) 2013 eBay Inc.
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
from cinder.openstack.common import log as logging


LOG = logging.getLogger(__name__)


class ViewBuilder(common.ViewBuilder):
    """Model QoS specs API responses as a python dictionary."""

    _collection_name = "qos_specs"

    def __init__(self):
        """Initialize view builder."""
        super(ViewBuilder, self).__init__()

    def summary_list(self, request, qos_specs):
        """Show a list of qos_specs without many details."""
        return self._list_view(self.detail, request, qos_specs)

    def summary(self, request, qos_spec):
        """Generic, non-detailed view of a qos_specs."""
        return {
            'qos_specs': qos_spec,
            'links': self._get_links(request,
                                     qos_spec['id']),
        }

    def detail(self, request, qos_spec):
        """Detailed view of a single qos_spec."""
        #TODO(zhiteng) Add associations to detailed view
        return {
            'qos_specs': qos_spec,
            'links': self._get_links(request,
                                     qos_spec['id']),
        }

    def associations(self, request, associates):
        """View of qos specs associations."""
        return {
            'qos_associations': associates
        }

    def _list_view(self, func, request, qos_specs):
        """Provide a view for a list of qos_specs."""
        specs_list = [func(request, specs)['qos_specs'] for specs in qos_specs]
        specs_dict = dict(qos_specs=specs_list)

        return specs_dict
