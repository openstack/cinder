# Copyright (C) 2012 Hewlett-Packard Development Company, L.P.
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

"""
Client side of the volume backup RPC API.
"""


from oslo_log import log as logging

from cinder.common import constants
from cinder import rpc


LOG = logging.getLogger(__name__)


class BackupAPI(rpc.RPCAPI):
    """Client side of the volume rpc API.

    API version history:

    .. code-block:: none

        1.0 - Initial version.
        1.1 - Changed methods to accept backup objects instead of IDs.
        1.2 - A version that got in by mistake (without breaking anything).
        1.3 - Dummy version bump to mark start of having cinder-backup service
              decoupled from cinder-volume.

        ... Mitaka supports messaging 1.3. Any changes to existing methods in
        1.x after this point should be done so that they can handle version cap
        set to 1.3.

        2.0 - Remove 1.x compatibility
        2.1 - Adds set_log_levels and get_log_levels
    """

    RPC_API_VERSION = '2.1'
    RPC_DEFAULT_VERSION = '2.0'
    TOPIC = constants.BACKUP_TOPIC
    BINARY = 'cinder-backup'

    def create_backup(self, ctxt, backup):
        LOG.debug("create_backup in rpcapi backup_id %s", backup.id)
        cctxt = self._get_cctxt(server=backup.host)
        cctxt.cast(ctxt, 'create_backup', backup=backup)

    def restore_backup(self, ctxt, volume_host, backup, volume_id):
        LOG.debug("restore_backup in rpcapi backup_id %s", backup.id)
        cctxt = self._get_cctxt(server=volume_host)
        cctxt.cast(ctxt, 'restore_backup', backup=backup,
                   volume_id=volume_id)

    def delete_backup(self, ctxt, backup):
        LOG.debug("delete_backup rpcapi backup_id %s", backup.id)
        cctxt = self._get_cctxt(server=backup.host)
        cctxt.cast(ctxt, 'delete_backup', backup=backup)

    def export_record(self, ctxt, backup):
        LOG.debug("export_record in rpcapi backup_id %(id)s "
                  "on host %(host)s.",
                  {'id': backup.id,
                   'host': backup.host})
        cctxt = self._get_cctxt(server=backup.host)
        return cctxt.call(ctxt, 'export_record', backup=backup)

    def import_record(self, ctxt, host, backup, backup_service, backup_url,
                      backup_hosts):
        LOG.debug("import_record rpcapi backup id %(id)s "
                  "on host %(host)s for backup_url %(url)s.",
                  {'id': backup.id, 'host': host, 'url': backup_url})
        cctxt = self._get_cctxt(server=host)
        cctxt.cast(ctxt, 'import_record',
                   backup=backup,
                   backup_service=backup_service,
                   backup_url=backup_url,
                   backup_hosts=backup_hosts)

    def reset_status(self, ctxt, backup, status):
        LOG.debug("reset_status in rpcapi backup_id %(id)s "
                  "on host %(host)s.",
                  {'id': backup.id, 'host': backup.host})
        cctxt = self._get_cctxt(server=backup.host)
        return cctxt.cast(ctxt, 'reset_status', backup=backup, status=status)

    def check_support_to_force_delete(self, ctxt, host):
        LOG.debug("Check if backup driver supports force delete "
                  "on host %(host)s.", {'host': host})
        cctxt = self._get_cctxt(server=host)
        return cctxt.call(ctxt, 'check_support_to_force_delete')

    @rpc.assert_min_rpc_version('2.1')
    def set_log_levels(self, context, service, log_request):
        cctxt = self._get_cctxt(server=service.host, version='2.1')
        cctxt.cast(context, 'set_log_levels', log_request=log_request)

    @rpc.assert_min_rpc_version('2.1')
    def get_log_levels(self, context, service, log_request):
        cctxt = self._get_cctxt(server=service.host, version='2.1')
        return cctxt.call(context, 'get_log_levels', log_request=log_request)
