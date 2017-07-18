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
    """Model an resource filters API response as a python dictionary."""

    _collection_name = "resource_filters"

    @classmethod
    def list(cls, filters):
        """Build a view of a list of resource filters.

         .. code-block:: json

            {
               "resource_filters": [{
                   "resource": "resource_1",
                   "filters": ["filter1", "filter2", "filter3"]
                }]
            }
        """

        return {'resource_filters': [{
            'resource': fil[0],
            'filters': fil[1]} for fil in filters.items()]}
