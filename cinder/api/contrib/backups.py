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

"""The backups api."""

import webob
from webob import exc
from xml.dom import minidom

from cinder.api import common
from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.api.views import backups as backup_views
from cinder.api import xmlutil
from cinder import backup as backupAPI
from cinder import exception
from cinder import flags
from cinder.openstack.common import log as logging

FLAGS = flags.FLAGS
LOG = logging.getLogger(__name__)


def make_backup(elem):
    elem.set('id')
    elem.set('status')
    elem.set('size')
    elem.set('container')
    elem.set('volume_id')
    elem.set('object_count')
    elem.set('availability_zone')
    elem.set('created_at')
    elem.set('name')
    elem.set('description')
    elem.set('fail_reason')


def make_backup_restore(elem):
    elem.set('backup_id')
    elem.set('volume_id')


class BackupTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('backup', selector='backup')
        make_backup(root)
        alias = Backups.alias
        namespace = Backups.namespace
        return xmlutil.MasterTemplate(root, 1, nsmap={alias: namespace})


class BackupsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('backups')
        elem = xmlutil.SubTemplateElement(root, 'backup', selector='backups')
        make_backup(elem)
        alias = Backups.alias
        namespace = Backups.namespace
        return xmlutil.MasterTemplate(root, 1, nsmap={alias: namespace})


class BackupRestoreTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('restore', selector='restore')
        make_backup_restore(root)
        alias = Backups.alias
        namespace = Backups.namespace
        return xmlutil.MasterTemplate(root, 1, nsmap={alias: namespace})


class CreateDeserializer(wsgi.MetadataXMLDeserializer):
    def default(self, string):
        dom = minidom.parseString(string)
        backup = self._extract_backup(dom)
        return {'body': {'backup': backup}}

    def _extract_backup(self, node):
        backup = {}
        backup_node = self.find_first_child_named(node, 'backup')

        attributes = ['container', 'display_name',
                      'display_description', 'volume_id']

        for attr in attributes:
            if backup_node.getAttribute(attr):
                backup[attr] = backup_node.getAttribute(attr)
        return backup


class RestoreDeserializer(wsgi.MetadataXMLDeserializer):
    def default(self, string):
        dom = minidom.parseString(string)
        restore = self._extract_restore(dom)
        return {'body': {'restore': restore}}

    def _extract_restore(self, node):
        restore = {}
        restore_node = self.find_first_child_named(node, 'restore')
        if restore_node.getAttribute('volume_id'):
            restore['volume_id'] = restore_node.getAttribute('volume_id')
        return restore


class BackupsController(wsgi.Controller):
    """The Backups API controller for the OpenStack API."""

    _view_builder_class = backup_views.ViewBuilder

    def __init__(self):
        self.backup_api = backupAPI.API()
        super(BackupsController, self).__init__()

    @wsgi.serializers(xml=BackupTemplate)
    def show(self, req, id):
        """Return data about the given backup."""
        LOG.debug(_('show called for member %s'), id)
        context = req.environ['cinder.context']

        try:
            backup = self.backup_api.get(context, backup_id=id)
        except exception.BackupNotFound as error:
            raise exc.HTTPNotFound(explanation=unicode(error))

        return self._view_builder.detail(req, backup)

    def delete(self, req, id):
        """Delete a backup."""
        LOG.debug(_('delete called for member %s'), id)
        context = req.environ['cinder.context']

        LOG.audit(_('Delete backup with id: %s'), id, context=context)

        try:
            self.backup_api.delete(context, id)
        except exception.BackupNotFound as error:
            raise exc.HTTPNotFound(explanation=unicode(error))
        except exception.InvalidBackup as error:
            raise exc.HTTPBadRequest(explanation=unicode(error))

        return webob.Response(status_int=202)

    @wsgi.serializers(xml=BackupsTemplate)
    def index(self, req):
        """Returns a summary list of backups."""
        return self._get_backups(req, is_detail=False)

    @wsgi.serializers(xml=BackupsTemplate)
    def detail(self, req):
        """Returns a detailed list of backups."""
        return self._get_backups(req, is_detail=True)

    def _get_backups(self, req, is_detail):
        """Returns a list of backups, transformed through view builder."""
        context = req.environ['cinder.context']
        backups = self.backup_api.get_all(context)
        limited_list = common.limited(backups, req)

        if is_detail:
            backups = self._view_builder.detail_list(req, limited_list)
        else:
            backups = self._view_builder.summary_list(req, limited_list)
        return backups

    # TODO(frankm): Add some checks here including
    # - whether requested volume_id exists so we can return some errors
    #   immediately
    # - maybe also do validation of swift container name
    @wsgi.response(202)
    @wsgi.serializers(xml=BackupTemplate)
    @wsgi.deserializers(xml=CreateDeserializer)
    def create(self, req, body):
        """Create a new backup."""
        LOG.debug(_('Creating new backup %s'), body)
        if not self.is_valid_body(body, 'backup'):
            raise exc.HTTPBadRequest()

        context = req.environ['cinder.context']

        try:
            backup = body['backup']
            volume_id = backup['volume_id']
        except KeyError:
            msg = _("Incorrect request body format")
            raise exc.HTTPBadRequest(explanation=msg)
        container = backup.get('container', None)
        name = backup.get('name', None)
        description = backup.get('description', None)

        LOG.audit(_("Creating backup of volume %(volume_id)s in container"
                    " %(container)s"), locals(), context=context)

        try:
            new_backup = self.backup_api.create(context, name, description,
                                                volume_id, container)
        except exception.InvalidVolume as error:
            raise exc.HTTPBadRequest(explanation=unicode(error))
        except exception.VolumeNotFound as error:
            raise exc.HTTPNotFound(explanation=unicode(error))

        retval = self._view_builder.summary(req, dict(new_backup.iteritems()))
        return retval

    @wsgi.response(202)
    @wsgi.serializers(xml=BackupRestoreTemplate)
    @wsgi.deserializers(xml=RestoreDeserializer)
    def restore(self, req, id, body):
        """Restore an existing backup to a volume."""
        backup_id = id
        LOG.debug(_('Restoring backup %(backup_id)s (%(body)s)') % locals())
        if not self.is_valid_body(body, 'restore'):
            raise exc.HTTPBadRequest()

        context = req.environ['cinder.context']

        try:
            restore = body['restore']
        except KeyError:
            msg = _("Incorrect request body format")
            raise exc.HTTPBadRequest(explanation=msg)
        volume_id = restore.get('volume_id', None)

        LOG.audit(_("Restoring backup %(backup_id)s to volume %(volume_id)s"),
                  locals(), context=context)

        try:
            new_restore = self.backup_api.restore(context,
                                                  backup_id=backup_id,
                                                  volume_id=volume_id)
        except exception.InvalidInput as error:
            raise exc.HTTPBadRequest(explanation=unicode(error))
        except exception.InvalidVolume as error:
            raise exc.HTTPBadRequest(explanation=unicode(error))
        except exception.InvalidBackup as error:
            raise exc.HTTPBadRequest(explanation=unicode(error))
        except exception.BackupNotFound as error:
            raise exc.HTTPNotFound(explanation=unicode(error))
        except exception.VolumeNotFound as error:
            raise exc.HTTPNotFound(explanation=unicode(error))
        except exception.VolumeSizeExceedsAvailableQuota as error:
            raise exc.HTTPRequestEntityTooLarge(
                explanation=error.message, headers={'Retry-After': 0})
        except exception.VolumeLimitExceeded as error:
            raise exc.HTTPRequestEntityTooLarge(
                explanation=error.message, headers={'Retry-After': 0})

        retval = self._view_builder.restore_summary(
            req, dict(new_restore.iteritems()))
        return retval


class Backups(extensions.ExtensionDescriptor):
    """Backups support."""

    name = 'Backups'
    alias = 'backups'
    namespace = 'http://docs.openstack.org/volume/ext/backups/api/v1'
    updated = '2012-12-12T00:00:00+00:00'

    def get_resources(self):
        resources = []
        res = extensions.ResourceExtension(
            Backups.alias, BackupsController(),
            collection_actions={'detail': 'GET'},
            member_actions={'restore': 'POST'})
        resources.append(res)
        return resources
