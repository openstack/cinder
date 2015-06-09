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

from oslo_log import log as logging


LOG = logging.getLogger(__name__)


class FakeBrickLVM(object):
    """Logs and records calls, for unit tests."""
    def __init__(self, vg_name, create, pv_list, vtype, execute=None):
        super(FakeBrickLVM, self).__init__()
        self.vg_size = '5.00'
        self.vg_free_space = '5.00'
        self.vg_name = vg_name

    def supports_thin_provisioning():
        return False

    def get_volumes(self):
        return ['fake-volume']

    def get_volume(self, name):
        return ['name']

    def get_all_physical_volumes(vg_name=None):
        return []

    def get_physical_volumes(self):
        return []

    def update_volume_group_info(self):
        pass

    def create_thin_pool(self, name=None, size_str=0):
        pass

    def create_volume(self, name, size_str, lv_type='default', mirror_count=0):
        pass

    def create_lv_snapshot(self, name, source_lv_name, lv_type='default'):
        pass

    def delete(self, name):
        pass

    def revert(self, snapshot_name):
        pass

    def lv_has_snapshot(self, name):
        return False

    def activate_lv(self, lv, is_snapshot=False):
        pass

    def rename_volume(self, lv_name, new_name):
        pass
