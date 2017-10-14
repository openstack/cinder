# Copyright 2016 EMC Corporation
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
from cinder.policies import group_types as policy


class ViewBuilder(common.ViewBuilder):

    def show(self, request, group_type, brief=False):
        """Trim away extraneous group type attributes."""
        context = request.environ['cinder.context']
        trimmed = dict(id=group_type.get('id'),
                       name=group_type.get('name'),
                       description=group_type.get('description'),
                       is_public=group_type.get('is_public'))
        if context.authorize(policy.SHOW_ACCESS_POLICY, fatal=False):
            trimmed['group_specs'] = group_type.get('group_specs')
        return trimmed if brief else dict(group_type=trimmed)

    def index(self, request, group_types):
        """Index over trimmed group types."""
        group_types_list = [self.show(request, group_type, True)
                            for group_type in group_types]
        group_type_links = self._get_collection_links(request, group_types,
                                                      'group_types')
        group_types_dict = dict(group_types=group_types_list)
        if group_type_links:
            group_types_dict['group_type_links'] = group_type_links
        return group_types_dict
