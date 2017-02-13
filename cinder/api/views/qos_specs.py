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


class ViewBuilder(common.ViewBuilder):
    """Model QoS specs API responses as a python dictionary."""

    _collection_name = "qos-specs"

    def __init__(self):
        """Initialize view builder."""
        super(ViewBuilder, self).__init__()

    def summary_list(self, request, qos_specs, qos_count=None):
        """Show a list of qos_specs without many details."""
        return self._list_view(self.detail, request, qos_specs, qos_count)

    def summary(self, request, qos_spec):
        """Generic, non-detailed view of a qos_specs."""
        return self.detail(request, qos_spec)

    def detail(self, request, qos_spec):
        """Detailed view of a single qos_spec."""
        # TODO(zhiteng) Add associations to detailed view
        return {
            'qos_specs': {
                'id': qos_spec.id,
                'name': qos_spec.name,
                'consumer': qos_spec.consumer,
                'specs': qos_spec.specs,
            },
            'links': self._get_links(request,
                                     qos_spec.id),
        }

    def associations(self, request, associates):
        """View of qos specs associations."""
        return {
            'qos_associations': associates
        }

    def _list_view(self, func, request, qos_specs, qos_count=None):
        """Provide a view for a list of qos_specs."""
        specs_list = [func(request, specs)['qos_specs'] for specs in qos_specs]
        specs_links = self._get_collection_links(request, qos_specs,
                                                 self._collection_name,
                                                 qos_count)
        specs_dict = dict(qos_specs=specs_list)
        if specs_links:
            specs_dict['qos_specs_links'] = specs_links

        return specs_dict
