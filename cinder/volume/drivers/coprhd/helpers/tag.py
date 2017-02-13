# Copyright (c) 2016 EMC Corporation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.


"""Contains tagging related methods."""

import oslo_serialization

from cinder.i18n import _
from cinder.volume.drivers.coprhd.helpers import commoncoprhdapi as common


class Tag(common.CoprHDResource):

    def tag_resource(self, uri, resource_id, add, remove):
        params = {
            'add': add,
            'remove': remove
        }

        body = oslo_serialization.jsonutils.dumps(params)

        (s, h) = common.service_json_request(self.ipaddr, self.port, "PUT",
                                             uri.format(resource_id), body)
        o = common.json_decode(s)
        return o

    def list_tags(self, resource_uri):
        if resource_uri.__contains__("tag") is False:
            raise common.CoprHdError(
                common.CoprHdError.VALUE_ERR, _("URI should end with /tag"))

        (s, h) = common.service_json_request(self.ipaddr,
                                             self.port,
                                             "GET",
                                             resource_uri,
                                             None)

        allTags = []
        o = common.json_decode(s)
        allTags = o['tag']

        return allTags
