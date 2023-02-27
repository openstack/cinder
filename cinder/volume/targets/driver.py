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

import abc

from oslo_config import cfg

from cinder import db

CONF = cfg.CONF


class Target(object, metaclass=abc.ABCMeta):
    """Target object for block storage devices.

    Base class for target object, where target
    is data transport mechanism (target) specific calls.
    This includes things like create targets, attach, detach
    etc.

    Base class here does nothing more than set an executor and db as
    well as force implementation of required methods.

    """
    storage_protocol = None
    SHARED_TARGET_SUPPORT = False
    SECONDARY_IP_SUPPORT = True

    def __init__(self, *args, **kwargs):
        # TODO(stephenfin): Drop this in favour of using 'db' directly
        self.db = db
        self.configuration = kwargs.get('configuration')
        self._root_helper = kwargs.get('root_helper',
                                       'sudo cinder-rootwrap %s' %
                                       CONF.rootwrap_config)

    @abc.abstractmethod
    def ensure_export(self, context, volume, volume_path):
        """Synchronously recreates an export for a volume."""
        pass

    @abc.abstractmethod
    def create_export(self, context, volume, volume_path):
        """Exports a Target/Volume.

        Can optionally return a Dict of changes to
        the volume object to be persisted.
        """
        pass

    @abc.abstractmethod
    def remove_export(self, context, volume):
        """Removes an export for a Target/Volume."""
        pass

    @abc.abstractmethod
    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info."""
        pass

    @abc.abstractmethod
    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector."""
        pass

    @staticmethod
    def are_same_connector(A, B):
        """Whether 2 connectors belong to the same host or not.

        This is used for multi attach volumes, to be able to know when there
        are no more attachments on a given host.

        This is the generic implementation, but specific targets may overwrite
        it. For example iSCSI would check the the "initiator" key instead, and
        NVMe-oF would check the "nqn" key.
        """
        a_host = A.get('host')
        return a_host and (a_host == B.get('host'))

    def extend_target(self, volume):
        """Reinitializes a target after the volume has been extended.

        Most drivers don't need to do anything, but in other cases this may
        cause IO disruption.
        """
        pass
