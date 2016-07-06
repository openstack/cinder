#   Copyright (c) 2016 Stratoscale, Ltd.
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.

from cinder.api import common


class ViewBuilder(common.ViewBuilder):
    """Model manageable volume responses as a python dictionary."""

    _collection_name = "os-volume-manage"

    def summary_list(self, request, volumes, count):
        """Show a list of manageable volumes without many details."""
        return self._list_view(self.summary, request, volumes, count)

    def detail_list(self, request, volumes, count):
        """Detailed view of a list of manageable volumes."""
        return self._list_view(self.detail, request, volumes, count)

    def summary(self, request, volume):
        """Generic, non-detailed view of a manageable volume description."""
        return {
            'reference': volume['reference'],
            'size': volume['size'],
            'safe_to_manage': volume['safe_to_manage']
        }

    def detail(self, request, volume):
        """Detailed view of a manageable volume description."""
        return {
            'reference': volume['reference'],
            'size': volume['size'],
            'safe_to_manage': volume['safe_to_manage'],
            'reason_not_safe': volume['reason_not_safe'],
            'cinder_id': volume['cinder_id'],
            'extra_info': volume['extra_info']
        }

    def _list_view(self, func, request, volumes, count):
        """Provide a view for a list of manageable volumes."""
        vol_list = [func(request, volume) for volume in volumes]
        return {"manageable-volumes": vol_list}
