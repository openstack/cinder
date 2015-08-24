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


from oslo_config import cfg
from oslo_log import log as logging
import oslo_messaging as messaging

from cinder.objects import base as objects_base
from cinder import rpc


CONF = cfg.CONF

LOG = logging.getLogger(__name__)


class BackupAPI(object):
    """Client side of the volume rpc API.

    API version history:

        1.0 - Initial version.
        1.1 - Changed methods to accept backup objects instead of IDs.
    """

    BASE_RPC_API_VERSION = '1.0'
    RPC_API_VERSION = '1.1'

    def __init__(self):
        super(BackupAPI, self).__init__()
        target = messaging.Target(topic=CONF.backup_topic,
                                  version=self.BASE_RPC_API_VERSION)
        serializer = objects_base.CinderObjectSerializer()
        self.client = rpc.get_client(target, self.RPC_API_VERSION,
                                     serializer=serializer)

    def create_backup(self, ctxt, backup):
        LOG.debug("create_backup in rpcapi backup_id %s", backup.id)
        cctxt = self.client.prepare(server=backup.host)
        cctxt.cast(ctxt, 'create_backup', backup=backup)

    def restore_backup(self, ctxt, volume_host, backup, volume_id):
        LOG.debug("restore_backup in rpcapi backup_id %s", backup.id)
        cctxt = self.client.prepare(server=volume_host)
        cctxt.cast(ctxt, 'restore_backup', backup=backup,
                   volume_id=volume_id)

    def delete_backup(self, ctxt, backup):
        LOG.debug("delete_backup  rpcapi backup_id %s", backup.id)
        cctxt = self.client.prepare(server=backup.host)
        cctxt.cast(ctxt, 'delete_backup', backup=backup)

    def export_record(self, ctxt, backup):
        LOG.debug("export_record in rpcapi backup_id %(id)s "
                  "on host %(host)s.",
                  {'id': backup.id,
                   'host': backup.host})
        cctxt = self.client.prepare(server=backup.host)
        return cctxt.call(ctxt, 'export_record', backup=backup)

    def import_record(self,
                      ctxt,
                      host,
                      backup,
                      backup_service,
                      backup_url,
                      backup_hosts):
        LOG.debug("import_record rpcapi backup id %(id)s "
                  "on host %(host)s for backup_url %(url)s.",
                  {'id': backup.id,
                   'host': host,
                   'url': backup_url})
        cctxt = self.client.prepare(server=host)
        cctxt.cast(ctxt, 'import_record',
                   backup=backup,
                   backup_service=backup_service,
                   backup_url=backup_url,
                   backup_hosts=backup_hosts)

    def reset_status(self, ctxt, backup, status):
        LOG.debug("reset_status in rpcapi backup_id %(id)s "
                  "on host %(host)s.",
                  {'id': backup.id,
                   'host': backup.host})
        cctxt = self.client.prepare(server=backup.host)
        return cctxt.cast(ctxt, 'reset_status', backup=backup, status=status)

    def check_support_to_force_delete(self, ctxt, host):
        LOG.debug("Check if backup driver supports force delete "
                  "on host %(host)s.", {'host': host})
        cctxt = self.client.prepare(server=host)
        return cctxt.call(ctxt, 'check_support_to_force_delete')
