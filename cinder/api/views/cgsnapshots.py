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
    """Model cgsnapshot API responses as a python dictionary."""

    _collection_name = "cgsnapshots"

    def __init__(self):
        """Initialize view builder."""
        super(ViewBuilder, self).__init__()

    def summary_list(self, request, cgsnapshots):
        """Show a list of cgsnapshots without many details."""
        return self._list_view(self.summary, request, cgsnapshots)

    def detail_list(self, request, cgsnapshots):
        """Detailed view of a list of cgsnapshots ."""
        return self._list_view(self.detail, request, cgsnapshots)

    def summary(self, request, cgsnapshot):
        """Generic, non-detailed view of a cgsnapshot."""
        return {
            'cgsnapshot': {
                'id': cgsnapshot['id'],
                'name': cgsnapshot['name']
            }
        }

    def detail(self, request, cgsnapshot):
        """Detailed view of a single cgsnapshot."""
        return {
            'cgsnapshot': {
                'id': cgsnapshot.get('id'),
                'consistencygroup_id': cgsnapshot.get('consistencygroup_id'),
                'status': cgsnapshot.get('status'),
                'created_at': cgsnapshot.get('created_at'),
                'name': cgsnapshot.get('name'),
                'description': cgsnapshot.get('description')
            }
        }

    def _list_view(self, func, request, cgsnapshots):
        """Provide a view for a list of cgsnapshots."""
        cgsnapshots_list = [func(request, cgsnapshot)['cgsnapshot']
                            for cgsnapshot in cgsnapshots]
        cgsnapshots_dict = dict(cgsnapshots=cgsnapshots_list)

        return cgsnapshots_dict
