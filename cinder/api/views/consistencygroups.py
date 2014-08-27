# Copyright (C) 2012 - 2014 EMC Corporation.
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
    """Model consistencygroup API responses as a python dictionary."""

    _collection_name = "consistencygroups"

    def __init__(self):
        """Initialize view builder."""
        super(ViewBuilder, self).__init__()

    def summary_list(self, request, consistencygroups):
        """Show a list of consistency groups without many details."""
        return self._list_view(self.summary, request, consistencygroups)

    def detail_list(self, request, consistencygroups):
        """Detailed view of a list of consistency groups ."""
        return self._list_view(self.detail, request, consistencygroups)

    def summary(self, request, consistencygroup):
        """Generic, non-detailed view of a consistency group."""
        return {
            'consistencygroup': {
                'id': consistencygroup['id'],
                'name': consistencygroup['name']
            }
        }

    def detail(self, request, consistencygroup):
        """Detailed view of a single consistency group."""
        return {
            'consistencygroup': {
                'id': consistencygroup.get('id'),
                'status': consistencygroup.get('status'),
                'availability_zone': consistencygroup.get('availability_zone'),
                'created_at': consistencygroup.get('created_at'),
                'name': consistencygroup.get('name'),
                'description': consistencygroup.get('description')
            }
        }

    def _list_view(self, func, request, consistencygroups):
        """Provide a view for a list of consistency groups."""
        consistencygroups_list = [
            func(request, consistencygroup)['consistencygroup']
            for consistencygroup in consistencygroups]
        consistencygroups_dict = dict(consistencygroups=consistencygroups_list)

        return consistencygroups_dict
