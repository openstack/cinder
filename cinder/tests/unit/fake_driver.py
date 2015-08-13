#    Copyright 2012 OpenStack Foundation
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

from cinder.tests.unit.brick import fake_lvm
from cinder.volume import driver
from cinder.volume.drivers import lvm
from cinder.zonemanager import utils as fczm_utils


class FakeISCSIDriver(lvm.LVMISCSIDriver):
    """Logs calls instead of executing."""
    def __init__(self, *args, **kwargs):
        super(FakeISCSIDriver, self).__init__(execute=self.fake_execute,
                                              *args, **kwargs)
        self.vg = fake_lvm.FakeBrickLVM('cinder-volumes', False,
                                        None, 'default',
                                        self.fake_execute)

    def check_for_setup_error(self):
        """No setup necessary in fake mode."""
        pass

    def initialize_connection(self, volume, connector):
        volume_metadata = {}

        for metadata in volume['volume_admin_metadata']:
            volume_metadata[metadata['key']] = metadata['value']

        access_mode = volume_metadata.get('attached_mode')
        if access_mode is None:
            access_mode = ('ro'
                           if volume_metadata.get('readonly') == 'True'
                           else 'rw')

        return {'driver_volume_type': 'iscsi',
                'data': {'access_mode': access_mode}}

    def terminate_connection(self, volume, connector, **kwargs):
        pass

    @staticmethod
    def fake_execute(cmd, *_args, **_kwargs):
        """Execute that simply logs the command."""
        return (None, None)


class FakeISERDriver(FakeISCSIDriver):
    """Logs calls instead of executing."""
    def __init__(self, *args, **kwargs):
        super(FakeISERDriver, self).__init__(execute=self.fake_execute,
                                             *args, **kwargs)

    def initialize_connection(self, volume, connector):
        return {
            'driver_volume_type': 'iser',
            'data': {}
        }

    @staticmethod
    def fake_execute(cmd, *_args, **_kwargs):
        """Execute that simply logs the command."""
        return (None, None)


class FakeFibreChannelDriver(driver.FibreChannelDriver):

    @fczm_utils.AddFCZone
    def initialize_connection(self, volume, connector):
        return {
            'driver_volume_type': 'fibre_channel',
            'data': {
                'initiator_target_map': {'fake_wwn': ['fake_wwn2']},
            }}

    @fczm_utils.AddFCZone
    def no_zone_initialize_connection(self, volume, connector):
        """This shouldn't call the ZM."""
        return {
            'driver_volume_type': 'bogus',
            'data': {
                'initiator_target_map': {'fake_wwn': ['fake_wwn2']},
            }}

    @fczm_utils.RemoveFCZone
    def terminate_connection(self, volume, connector, **kwargs):
        return {
            'driver_volume_type': 'fibre_channel',
            'data': {
                'initiator_target_map': {'fake_wwn': ['fake_wwn2']},
            }}

    @fczm_utils.RemoveFCZone
    def no_zone_terminate_connection(self, volume, connector, **kwargs):
        return {
            'driver_volume_type': 'bogus',
            'data': {
                'initiator_target_map': {'fake_wwn': ['fake_wwn2']},
            }}


class LoggingVolumeDriver(driver.VolumeDriver):
    """Logs and records calls, for unit tests."""

    def check_for_setup_error(self):
        pass

    def create_volume(self, volume):
        self.log_action('create_volume', volume)

    def delete_volume(self, volume):
        self.clear_volume(volume)
        self.log_action('delete_volume', volume)

    def clear_volume(self, volume):
        self.log_action('clear_volume', volume)

    def local_path(self, volume):
        raise NotImplementedError()

    def ensure_export(self, context, volume):
        self.log_action('ensure_export', volume)

    def create_export(self, context, volume):
        self.log_action('create_export', volume)

    def remove_export(self, context, volume):
        self.log_action('remove_export', volume)

    def initialize_connection(self, volume, connector):
        self.log_action('initialize_connection', volume)

    def terminate_connection(self, volume, connector):
        self.log_action('terminate_connection', volume)

    def create_export_snapshot(self, context, snapshot):
        self.log_action('create_export_snapshot', snapshot)

    def remove_export_snapshot(self, context, snapshot):
        self.log_action('remove_export_snapshot', snapshot)

    def initialize_connection_snapshot(self, snapshot, connector):
        self.log_action('initialize_connection_snapshot', snapshot)

    def terminate_connection_snapshot(self, snapshot, connector):
        self.log_action('terminate_connection_snapshot', snapshot)

    def create_cloned_volume(self, volume, src_vol):
        self.log_action('create_cloned_volume', volume)

    _LOGS = []

    @staticmethod
    def clear_logs():
        LoggingVolumeDriver._LOGS = []

    @staticmethod
    def log_action(action, parameters):
        """Logs the command."""
        log_dictionary = {}
        if parameters:
            log_dictionary = dict(parameters)
        log_dictionary['action'] = action
        LoggingVolumeDriver._LOGS.append(log_dictionary)

    @staticmethod
    def all_logs():
        return LoggingVolumeDriver._LOGS

    @staticmethod
    def logs_like(action, **kwargs):
        matches = []
        for entry in LoggingVolumeDriver._LOGS:
            if entry['action'] != action:
                continue
            match = True
            for k, v in kwargs.items():
                if entry.get(k) != v:
                    match = False
                    break
            if match:
                matches.append(entry)
        return matches
