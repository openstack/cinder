# Copyright 2020 Red Hat, Inc.
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


class ViewBuilder(object):
    """Model default type API response as a python dictionary."""

    _collection_name = "default_types"

    def _convert_to_dict(self, default):
        return {'project_id': default.project_id,
                'volume_type_id': default.volume_type_id}

    def create(self, default_type):
        """Detailed view of a default type when set."""

        return {'default_type': self._convert_to_dict(default_type)}

    def index(self, default_types):
        """Build a view of a list of default types.

         .. code-block:: json

             {"default_types":
                [
                 {
                   "project_id": "248592b4-a6da-4c4c-abe0-9d8dbe0b74b4",
                   "volume_type_id": "7152eb1e-aef0-4bcd-a3ab-46b7ef17e2e6"
                 },
                 {
                   "project_id": "1234567-4c4c-abcd-abe0-1a2b3c4d5e6ff",
                   "volume_type_id": "5e3b298a-f1fc-4d32-9828-0d720da81ddd"
                 }
             ]
             }
        """

        default_types_view = []
        for default_type in default_types:
            default_types_view.append(self._convert_to_dict(default_type))

        return {'default_types': default_types_view}

    def detail(self, default_type):
        """Build a view of a default type.

         .. code-block:: json

             {"default_type":
                 {
                   "project_id": "248592b4-a6da-4c4c-abe0-9d8dbe0b74b4",
                   "volume_type_id": "6bd1de9a-b8b5-4c43-a597-00170ab06b50"
                 }
             }
        """
        return {'default_type': self._convert_to_dict(default_type)}
