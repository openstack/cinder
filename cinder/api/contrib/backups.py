# Copyright (C) 2012 Hewlett-Packard Development Company, L.P.
# Copyright (c) 2014 TrilioData, Inc
# Copyright (c) 2015 EMC Corporation
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

"""The backups api."""

from oslo_log import log as logging
from six.moves import http_client
from webob import exc

from cinder.api import common
from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.api.views import backups as backup_views
from cinder import backup as backupAPI
from cinder import exception
from cinder.i18n import _
from cinder import utils

LOG = logging.getLogger(__name__)


class BackupsController(wsgi.Controller):
    """The Backups API controller for the OpenStack API."""

    _view_builder_class = backup_views.ViewBuilder

    def __init__(self):
        self.backup_api = backupAPI.API()
        super(BackupsController, self).__init__()

    def show(self, req, id):
        """Return data about the given backup."""
        LOG.debug('Show backup with id: %s.', id)
        context = req.environ['cinder.context']

        # Not found exception will be handled at the wsgi level
        backup = self.backup_api.get(context, backup_id=id)
        req.cache_db_backup(backup)

        return self._view_builder.detail(req, backup)

    @wsgi.response(http_client.ACCEPTED)
    def delete(self, req, id):
        """Delete a backup."""
        context = req.environ['cinder.context']

        LOG.info('Delete backup with id: %s.', id)

        try:
            backup = self.backup_api.get(context, id)
            self.backup_api.delete(context, backup)
        # Not found exception will be handled at the wsgi level
        except exception.InvalidBackup as error:
            raise exc.HTTPBadRequest(explanation=error.msg)

    def index(self, req):
        """Returns a summary list of backups."""
        return self._get_backups(req, is_detail=False)

    def detail(self, req):
        """Returns a detailed list of backups."""
        return self._get_backups(req, is_detail=True)

    @staticmethod
    def _get_backup_filter_options():
        """Return volume search options allowed by non-admin."""
        return ('name', 'status', 'volume_id')

    @common.process_general_filtering('backup')
    def _process_backup_filtering(self, context=None, filters=None,
                                  req_version=None):
        utils.remove_invalid_filter_options(context,
                                            filters,
                                            self._get_backup_filter_options())

    def _convert_sort_name(self, req_version, sort_keys):
        """Convert sort key "name" to "display_name". """
        pass

    def _get_backups(self, req, is_detail):
        """Returns a list of backups, transformed through view builder."""
        context = req.environ['cinder.context']
        filters = req.params.copy()
        req_version = req.api_version_request
        marker, limit, offset = common.get_pagination_params(filters)
        sort_keys, sort_dirs = common.get_sort_params(filters)

        self._convert_sort_name(req_version, sort_keys)
        self._process_backup_filtering(context=context, filters=filters,
                                       req_version=req_version)

        if 'name' in filters:
            filters['display_name'] = filters.pop('name')

        backups = self.backup_api.get_all(context, search_opts=filters,
                                          marker=marker,
                                          limit=limit,
                                          offset=offset,
                                          sort_keys=sort_keys,
                                          sort_dirs=sort_dirs,
                                          )

        req.cache_db_backups(backups.objects)

        if is_detail:
            backups = self._view_builder.detail_list(req, backups.objects)
        else:
            backups = self._view_builder.summary_list(req, backups.objects)
        return backups

    # TODO(frankm): Add some checks here including
    # - whether requested volume_id exists so we can return some errors
    #   immediately
    # - maybe also do validation of swift container name
    @wsgi.response(http_client.ACCEPTED)
    def create(self, req, body):
        """Create a new backup."""
        LOG.debug('Creating new backup %s', body)
        self.assert_valid_body(body, 'backup')

        context = req.environ['cinder.context']
        backup = body['backup']
        req_version = req.api_version_request

        try:
            volume_id = backup['volume_id']
        except KeyError:
            msg = _("Incorrect request body format")
            raise exc.HTTPBadRequest(explanation=msg)
        container = backup.get('container', None)
        if container:
            utils.check_string_length(container, 'Backup container',
                                      min_length=0, max_length=255)
        self.validate_name_and_description(backup)
        name = backup.get('name', None)
        description = backup.get('description', None)
        incremental = backup.get('incremental', False)
        force = backup.get('force', False)
        snapshot_id = backup.get('snapshot_id', None)
        metadata = backup.get(
            'metadata', None) if req_version.matches("3.43") else None
        LOG.info("Creating backup of volume %(volume_id)s in container"
                 " %(container)s",
                 {'volume_id': volume_id, 'container': container},
                 context=context)

        try:
            new_backup = self.backup_api.create(context, name, description,
                                                volume_id, container,
                                                incremental, None, force,
                                                snapshot_id, metadata)
        except (exception.InvalidVolume,
                exception.InvalidSnapshot,
                exception.InvalidVolumeMetadata,
                exception.InvalidVolumeMetadataSize) as error:
            raise exc.HTTPBadRequest(explanation=error.msg)
        # Other not found exceptions will be handled at the wsgi level
        except exception.ServiceNotFound as error:
            raise exc.HTTPServiceUnavailable(explanation=error.msg)

        retval = self._view_builder.summary(req, dict(new_backup))
        return retval

    @wsgi.response(http_client.ACCEPTED)
    def restore(self, req, id, body):
        """Restore an existing backup to a volume."""
        LOG.debug('Restoring backup %(backup_id)s (%(body)s)',
                  {'backup_id': id, 'body': body})
        self.assert_valid_body(body, 'restore')

        context = req.environ['cinder.context']
        restore = body['restore']
        volume_id = restore.get('volume_id', None)
        name = restore.get('name', None)

        LOG.info("Restoring backup %(backup_id)s to volume %(volume_id)s.",
                 {'backup_id': id, 'volume_id': volume_id},
                 context=context)

        try:
            new_restore = self.backup_api.restore(context,
                                                  backup_id=id,
                                                  volume_id=volume_id,
                                                  name=name)
        # Not found exception will be handled at the wsgi level
        except (exception.InvalidInput,
                exception.InvalidVolume,
                exception.InvalidBackup) as error:
            raise exc.HTTPBadRequest(explanation=error.msg)
        except (exception.VolumeSizeExceedsAvailableQuota,
                exception.VolumeLimitExceeded) as error:
            raise exc.HTTPRequestEntityTooLarge(
                explanation=error.msg, headers={'Retry-After': '0'})

        retval = self._view_builder.restore_summary(
            req, dict(new_restore))
        return retval

    def export_record(self, req, id):
        """Export a backup."""
        LOG.debug('Export record for backup %s.', id)
        context = req.environ['cinder.context']

        try:
            backup_info = self.backup_api.export_record(context, id)
        # Not found exception will be handled at the wsgi level
        except exception.InvalidBackup as error:
            raise exc.HTTPBadRequest(explanation=error.msg)

        retval = self._view_builder.export_summary(
            req, dict(backup_info))
        LOG.debug('Exported record output: %s.', retval)
        return retval

    @wsgi.response(http_client.CREATED)
    def import_record(self, req, body):
        """Import a backup."""
        LOG.debug('Importing record from %s.', body)
        self.assert_valid_body(body, 'backup-record')
        context = req.environ['cinder.context']
        import_data = body['backup-record']
        # Verify that body elements are provided
        try:
            backup_service = import_data['backup_service']
            backup_url = import_data['backup_url']
        except KeyError:
            msg = _("Incorrect request body format.")
            raise exc.HTTPBadRequest(explanation=msg)
        LOG.debug('Importing backup using %(service)s and url %(url)s.',
                  {'service': backup_service, 'url': backup_url})

        try:
            new_backup = self.backup_api.import_record(context,
                                                       backup_service,
                                                       backup_url)
        except exception.InvalidBackup as error:
            raise exc.HTTPBadRequest(explanation=error.msg)
        # Other Not found exceptions will be handled at the wsgi level
        except exception.ServiceNotFound as error:
            raise exc.HTTPServiceUnavailable(explanation=error.msg)

        retval = self._view_builder.summary(req, dict(new_backup))
        LOG.debug('Import record output: %s.', retval)
        return retval


class Backups(extensions.ExtensionDescriptor):
    """Backups support."""

    name = 'Backups'
    alias = 'backups'
    updated = '2012-12-12T00:00:00+00:00'

    def get_resources(self):
        resources = []
        res = extensions.ResourceExtension(
            Backups.alias, BackupsController(),
            collection_actions={'detail': 'GET', 'import_record': 'POST'},
            member_actions={'restore': 'POST', 'export_record': 'GET',
                            'action': 'POST'})
        resources.append(res)
        return resources
