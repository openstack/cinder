# Copyright 2022 Red Hat, Inc.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from castellan.common.credentials import keystone_password
from castellan.common import exception as castellan_exception
from castellan import key_manager as castellan_key_manager
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils

from cinder import context
from cinder import objects

LOG = logging.getLogger(__name__)

CONF = cfg.CONF


class KeyTransfer(object):
    def __init__(self, conf: cfg.ConfigOpts):
        self.conf = conf
        self._service_context = keystone_password.KeystonePassword(
            password=conf.keystone_authtoken.password,
            auth_url=conf.keystone_authtoken.auth_url,
            username=conf.keystone_authtoken.username,
            user_domain_name=conf.keystone_authtoken.user_domain_name,
            project_name=conf.keystone_authtoken.project_name,
            project_domain_name=conf.keystone_authtoken.project_domain_name)

    @property
    def service_context(self):
        """Returns the cinder service's context."""
        return self._service_context

    def transfer_key(self,
                     volume: objects.volume.Volume,
                     src_context: context.RequestContext,
                     dst_context: context.RequestContext) -> None:
        """Transfer the key from the src_context to the dst_context."""
        key_manager = castellan_key_manager.API(self.conf)

        old_encryption_key_id = volume.encryption_key_id
        secret = key_manager.get(src_context, old_encryption_key_id)
        try:
            new_encryption_key_id = key_manager.store(dst_context, secret)
        except castellan_exception.KeyManagerError:
            with excutils.save_and_reraise_exception():
                LOG.error("Failed to transfer the encryption key. This is "
                          "likely because the cinder service lacks the "
                          "privilege to create secrets.")

        volume.encryption_key_id = new_encryption_key_id
        volume.save()

        snapshots = objects.snapshot.SnapshotList.get_all_for_volume(
            context.get_admin_context(),
            volume.id)
        for snapshot in snapshots:
            snapshot.encryption_key_id = new_encryption_key_id
            snapshot.save()

        key_manager.delete(src_context, old_encryption_key_id)


def transfer_create(context: context.RequestContext,
                    volume: objects.volume.Volume,
                    conf: cfg.ConfigOpts = CONF) -> None:
    """Transfer the key from the owner to the cinder service."""
    LOG.info("Initiating transfer of encryption key for volume %s", volume.id)
    key_transfer = KeyTransfer(conf)
    key_transfer.transfer_key(volume,
                              src_context=context,
                              dst_context=key_transfer.service_context)


def transfer_accept(context: context.RequestContext,
                    volume: objects.volume.Volume,
                    conf: cfg.ConfigOpts = CONF) -> None:
    """Transfer the key from the cinder service to the recipient."""
    LOG.info("Accepting transfer of encryption key for volume %s", volume.id)
    key_transfer = KeyTransfer(conf)
    key_transfer.transfer_key(volume,
                              src_context=key_transfer.service_context,
                              dst_context=context)


def transfer_delete(context: context.RequestContext,
                    volume: objects.volume.Volume,
                    conf: cfg.ConfigOpts = CONF) -> None:
    """Transfer the key from the cinder service back to the owner."""
    LOG.info("Cancelling transfer of encryption key for volume %s", volume.id)
    key_transfer = KeyTransfer(conf)
    key_transfer.transfer_key(volume,
                              src_context=key_transfer.service_context,
                              dst_context=context)
