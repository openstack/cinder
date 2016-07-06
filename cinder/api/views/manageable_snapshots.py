#  Copyright (c) 2016 Stratoscale, Ltd.
#
#  Licensed under the Apache License, Version 2.0 (the "License"); you may
#  not use this file except in compliance with the License. You may obtain
#  a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#  WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#  License for the specific language governing permissions and limitations
#  under the License.

from cinder.api import common


class ViewBuilder(common.ViewBuilder):
    """Model manageable snapshot responses as a python dictionary."""

    _collection_name = "os-snapshot-manage"

    def summary_list(self, request, snapshots, count):
        """Show a list of manageable snapshots without many details."""
        return self._list_view(self.summary, request, snapshots, count)

    def detail_list(self, request, snapshots, count):
        """Detailed view of a list of manageable snapshots."""
        return self._list_view(self.detail, request, snapshots, count)

    def summary(self, request, snapshot):
        """Generic, non-detailed view of a manageable snapshot description."""
        return {
            'reference': snapshot['reference'],
            'size': snapshot['size'],
            'safe_to_manage': snapshot['safe_to_manage'],
            'source_reference': snapshot['source_reference']
        }

    def detail(self, request, snapshot):
        """Detailed view of a manageable snapshot description."""
        return {
            'reference': snapshot['reference'],
            'size': snapshot['size'],
            'safe_to_manage': snapshot['safe_to_manage'],
            'reason_not_safe': snapshot['reason_not_safe'],
            'extra_info': snapshot['extra_info'],
            'cinder_id': snapshot['cinder_id'],
            'source_reference': snapshot['source_reference']
        }

    def _list_view(self, func, request, snapshots, count):
        """Provide a view for a list of manageable snapshots."""
        snap_list = [func(request, snapshot) for snapshot in snapshots]
        return {"manageable-snapshots": snap_list}
