#
# Copyright (c) 2016 NEC Corporation.
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

"""Drivers for M-Series Storage."""

from cinder import interface
from cinder.volume import driver
from cinder.volume.drivers.nec import volume_common
from cinder.volume.drivers.nec import volume_helper
from cinder.zonemanager import utils as fczm_utils


@interface.volumedriver
class MStorageISCSIDriver(volume_helper.MStorageDSVDriver,
                          driver.ISCSIDriver):
    """M-Series Storage Snapshot iSCSI Driver.

    .. code-block:: none

      Version history:

        1.8.1 - First open source driver version.
        1.8.2 - Code refactoring.
        1.9.1 - Support optimal path for non-disruptive backup.
        1.9.2 - Support manage/unmanage and manage/unmanage snapshot.
                Delete an unused configuration
                parameter (ldset_controller_node_name).
                Fixed bug #1705001: driver fails to start.
        1.10.1 - Support automatic configuration of SAN access control.
                 Fixed bug #1753375: SAN access remains permitted on the
                 source node.
        1.10.2 - Delete max volumes per pool limit.
        1.10.3 - Add faster clone status check.
                 Fixed bug #1777385: driver removed access permission from
                 the destination node after live-migraion.
                 Fixed bug #1778669: LUNs of detached volumes are never reused.
        1.11.1 - Add support python 3.
                 Add support for multi-attach.
                 Add support of more than 4 iSCSI portals for a node.
                 Add support to revert a volume to a snapshot.
                 Add support storage assist retype and fixed bug #1838955:
                 a volume in NEC Storage was left undeleted when the volume
                 was retyped to another storage.
    """

    VERSION = '1.11.1'
    CI_WIKI_NAME = 'NEC_Cinder_CI'

    def __init__(self, *args, **kwargs):
        super(MStorageISCSIDriver, self).__init__(*args, **kwargs)
        self._set_config(self.configuration, self.host,
                         self.__class__.__name__)

    @staticmethod
    def get_driver_options():
        return volume_common.mstorage_opts

    def ensure_export(self, context, volume):
        pass

    def get_volume_stats(self, refresh=False):
        return self.iscsi_get_volume_stats(refresh)

    def initialize_connection(self, volume, connector):
        return self.iscsi_initialize_connection(volume, connector)

    def terminate_connection(self, volume, connector, **kwargs):
        return self.iscsi_terminate_connection(volume, connector)

    def initialize_connection_snapshot(self, snapshot, connector, **kwargs):
        return self.iscsi_initialize_connection_snapshot(snapshot,
                                                         connector,
                                                         **kwargs)

    def terminate_connection_snapshot(self, snapshot, connector, **kwargs):
        return self.iscsi_terminate_connection_snapshot(snapshot,
                                                        connector,
                                                        **kwargs)


@interface.volumedriver
class MStorageFCDriver(volume_helper.MStorageDSVDriver,
                       driver.FibreChannelDriver):
    """M-Series Storage Snapshot FC Driver.

    .. code-block:: none

      Version history:

        1.8.1 - First open source driver version.
        1.8.2 - Code refactoring.
        1.9.1 - Support optimal path for non-disruptive backup.
        1.9.2 - Support manage/unmanage and manage/unmanage snapshot.
                Delete an unused configuration
                parameter (ldset_controller_node_name).
                Fixed bug #1705001: driver fails to start.
        1.10.1 - Support automatic configuration of SAN access control.
                 Fixed bug #1753375: SAN access remains permitted on the
                 source node.
        1.10.2 - Delete max volumes per pool limit.
        1.10.3 - Add faster clone status check.
                 Fixed bug #1777385: driver removed access permission from
                 the destination node after live-migraion.
                 Fixed bug #1778669: LUNs of detached volumes are never reused.
        1.11.1 - Add support python 3.
                 Add support for multi-attach.
                 Add support of more than 4 iSCSI portals for a node.
                 Add support to revert a volume to a snapshot.
                 Add support storage assist retype and fixed bug #1838955:
                 a volume in NEC Storage was left undeleted when the volume
                 was retyped to another storage.
    """

    VERSION = '1.11.1'
    CI_WIKI_NAME = 'NEC_Cinder_CI'

    def __init__(self, *args, **kwargs):
        super(MStorageFCDriver, self).__init__(*args, **kwargs)
        self._set_config(self.configuration, self.host,
                         self.__class__.__name__)

    @staticmethod
    def get_driver_options():
        return volume_common.mstorage_opts

    def ensure_export(self, context, volume):
        pass

    def get_volume_stats(self, refresh=False):
        return self.fc_get_volume_stats(refresh)

    def initialize_connection(self, volume, connector):
        conn_info = self.fc_initialize_connection(volume, connector)
        fczm_utils.add_fc_zone(conn_info)
        return conn_info

    def terminate_connection(self, volume, connector, **kwargs):
        conn_info = self.fc_terminate_connection(volume, connector)
        fczm_utils.remove_fc_zone(conn_info)
        return conn_info

    def initialize_connection_snapshot(self, snapshot, connector, **kwargs):
        return self.fc_initialize_connection_snapshot(snapshot,
                                                      connector,
                                                      **kwargs)

    def terminate_connection_snapshot(self, snapshot, connector, **kwargs):
        return self.fc_terminate_connection_snapshot(snapshot,
                                                     connector,
                                                     **kwargs)
