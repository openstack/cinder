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

    def ensure_export(self, context, volume, volume_path):
        pass

    def create_export(self, context, volume, volume_path):
        return {
            'location': "fake_location",
            'auth': "fake_auth"
        }

    def remove_export(self, context, volume):
        pass

    def initialize_connection(self, volume, connector):
        pass

    def terminate_connection(self, volume, connector, **kwargs):
        pass
