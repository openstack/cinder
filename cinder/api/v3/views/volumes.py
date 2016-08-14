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
    """Model a server API response as a python dictionary."""

    def quick_summary(self, volume_count, volume_size):
        """Number of volumes and size of volumes."""
        return {
            'volume-summary': {
                'total_count': volume_count,
                'total_size': volume_size
            },
        }
