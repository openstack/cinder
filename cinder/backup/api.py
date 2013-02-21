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
Handles all requests relating to the volume backups service.
"""

from eventlet import greenthread

from cinder.backup import rpcapi as backup_rpcapi
from cinder.db import base
from cinder import exception
from cinder import flags
from cinder.openstack.common import log as logging
import cinder.volume


FLAGS = flags.FLAGS

LOG = logging.getLogger(__name__)


class API(base.Base):
    """API for interacting with the volume backup manager."""

    def __init__(self, db_driver=None):
        self.backup_rpcapi = backup_rpcapi.BackupAPI()
        self.volume_api = cinder.volume.API()
        super(API, self).__init__(db_driver)

    def get(self, context, backup_id):
        rv = self.db.backup_get(context, backup_id)
        return dict(rv.iteritems())

    def delete(self, context, backup_id):
        """
        Make the RPC call to delete a volume backup.
        """
        backup = self.get(context, backup_id)
        if backup['status'] not in ['available', 'error']:
            msg = _('Backup status must be available or error')
            raise exception.InvalidBackup(reason=msg)

        self.db.backup_update(context, backup_id, {'status': 'deleting'})
        self.backup_rpcapi.delete_backup(context,
                                         backup['host'],
                                         backup['id'])

    # TODO(moorehef): Add support for search_opts, discarded atm
    def get_all(self, context, search_opts={}):
        if context.is_admin:
            backups = self.db.backup_get_all(context)
        else:
            backups = self.db.backup_get_all_by_project(context,
                                                        context.project_id)

        return backups

    def create(self, context, name, description, volume_id,
               container, availability_zone=None):
        """
        Make the RPC call to create a volume backup.
        """
        volume = self.volume_api.get(context, volume_id)
        if volume['status'] != "available":
            msg = _('Volume to be backed up must be available')
            raise exception.InvalidVolume(reason=msg)
        self.db.volume_update(context, volume_id, {'status': 'backing-up'})

        options = {'user_id': context.user_id,
                   'project_id': context.project_id,
                   'display_name': name,
                   'display_description': description,
                   'volume_id': volume_id,
                   'status': 'creating',
                   'container': container,
                   'size': volume['size'],
                   # TODO(DuncanT): This will need de-managling once
                   #                multi-backend lands
                   'host': volume['host'], }

        backup = self.db.backup_create(context, options)

        #TODO(DuncanT): In future, when we have a generic local attach,
        #               this can go via the scheduler, which enables
        #               better load ballancing and isolation of services
        self.backup_rpcapi.create_backup(context,
                                         backup['host'],
                                         backup['id'],
                                         volume_id)

        return backup

    def restore(self, context, backup_id, volume_id=None):
        """
        Make the RPC call to restore a volume backup.
        """
        backup = self.get(context, backup_id)
        if backup['status'] != 'available':
            msg = _('Backup status must be available')
            raise exception.InvalidBackup(reason=msg)

        size = backup['size']
        if size is None:
            msg = _('Backup to be restored has invalid size')
            raise exception.InvalidBackup(reason=msg)

        # Create a volume if none specified. If a volume is specified check
        # it is large enough for the backup
        if volume_id is None:
            name = 'restore_backup_%s' % backup_id
            description = 'auto-created_from_restore_from_swift'

            LOG.audit(_("Creating volume of %(size)s GB for restore of "
                        "backup %(backup_id)s"), locals(), context=context)
            volume = self.volume_api.create(context, size, name, description)
            volume_id = volume['id']

            while True:
                volume = self.volume_api.get(context, volume_id)
                if volume['status'] != 'creating':
                    break
                greenthread.sleep(1)
        else:
            volume = self.volume_api.get(context, volume_id)
            volume_size = volume['size']
            if volume_size < size:
                err = _('volume size %(volume_size)d is too small to restore '
                        'backup of size %(size)d.') % locals()
                raise exception.InvalidVolume(reason=err)

        if volume['status'] != "available":
            msg = _('Volume to be restored to must be available')
            raise exception.InvalidVolume(reason=msg)

        LOG.debug('Checking backup size %s against volume size %s',
                  size, volume['size'])
        if size > volume['size']:
            msg = _('Volume to be restored to is smaller '
                    'than the backup to be restored')
            raise exception.InvalidVolume(reason=msg)

        LOG.audit(_("Overwriting volume %(volume_id)s with restore of "
                    "backup %(backup_id)s"), locals(), context=context)

        # Setting the status here rather than setting at start and unrolling
        # for each error condition, it should be a very small window
        self.db.backup_update(context, backup_id, {'status': 'restoring'})
        self.db.volume_update(context, volume_id, {'status':
                                                   'restoring-backup'})
        self.backup_rpcapi.restore_backup(context,
                                          backup['host'],
                                          backup['id'],
                                          volume_id)

        d = {'backup_id': backup_id,
             'volume_id': volume_id, }

        return d
