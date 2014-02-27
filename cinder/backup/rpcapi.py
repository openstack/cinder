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


from oslo.config import cfg

from cinder.openstack.common import log as logging
from cinder.openstack.common import rpc
import cinder.openstack.common.rpc.proxy


CONF = cfg.CONF

LOG = logging.getLogger(__name__)


class BackupAPI(cinder.openstack.common.rpc.proxy.RpcProxy):
    """Client side of the volume rpc API.

    API version history:

        1.0 - Initial version.
    """

    BASE_RPC_API_VERSION = '1.0'

    def __init__(self):
        super(BackupAPI, self).__init__(
            topic=CONF.backup_topic,
            default_version=self.BASE_RPC_API_VERSION)

    def create_backup(self, ctxt, host, backup_id, volume_id):
        LOG.debug("create_backup in rpcapi backup_id %s", backup_id)
        topic = rpc.queue_get_for(ctxt, self.topic, host)
        LOG.debug("create queue topic=%s", topic)
        self.cast(ctxt,
                  self.make_msg('create_backup',
                                backup_id=backup_id),
                  topic=topic)

    def restore_backup(self, ctxt, host, backup_id, volume_id):
        LOG.debug("restore_backup in rpcapi backup_id %s", backup_id)
        topic = rpc.queue_get_for(ctxt, self.topic, host)
        LOG.debug("restore queue topic=%s", topic)
        self.cast(ctxt,
                  self.make_msg('restore_backup',
                                backup_id=backup_id,
                                volume_id=volume_id),
                  topic=topic)

    def delete_backup(self, ctxt, host, backup_id):
        LOG.debug("delete_backup rpcapi backup_id %s", backup_id)
        topic = rpc.queue_get_for(ctxt, self.topic, host)
        self.cast(ctxt,
                  self.make_msg('delete_backup',
                                backup_id=backup_id),
                  topic=topic)

    def export_record(self, ctxt, host, backup_id):
        LOG.debug("export_record in rpcapi backup_id %(id)s "
                  "on host %(host)s.",
                  {'id': backup_id,
                   'host': host})
        topic = rpc.queue_get_for(ctxt, self.topic, host)
        LOG.debug("export queue topic=%s" % topic)
        return self.call(ctxt,
                         self.make_msg('export_record',
                                       backup_id=backup_id),
                         topic=topic)

    def import_record(self,
                      ctxt,
                      host,
                      backup_id,
                      backup_service,
                      backup_url,
                      backup_hosts):
        LOG.debug("import_record rpcapi backup id $(id)s "
                  "on host %(host)s "
                  "for backup_url %(url)s." % {'id': backup_id,
                                               'host': host,
                                               'url': backup_url})
        topic = rpc.queue_get_for(ctxt, self.topic, host)
        self.cast(ctxt,
                  self.make_msg('import_record',
                                backup_id=backup_id,
                                backup_service=backup_service,
                                backup_url=backup_url,
                                backup_hosts=backup_hosts),
                  topic=topic)
