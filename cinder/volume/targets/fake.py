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

from cinder.volume.targets import iscsi


class FakeTarget(iscsi.ISCSITarget):
    VERSION = '0.1'

    def __init__(self, *args, **kwargs):
        super(FakeTarget, self).__init__(*args, **kwargs)

    def _get_target_and_lun(self, context, volume):
        return(0, 0)

    def create_iscsi_target(self, name, tid, lun, path,
                            chap_auth, **kwargs):
        pass

    def remove_iscsi_target(self, tid, lun, vol_id, vol_name, **kwargs):
        pass

    def _get_iscsi_target(self, context, vol_id):
        pass

    def _get_target(self, iqn):
        pass
