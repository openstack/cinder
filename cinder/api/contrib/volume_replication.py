# Copyright 2014 IBM Corp.
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

from oslo_log import log as logging
import six
import webob
from webob import exc

from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.api import xmlutil
from cinder import exception
from cinder.i18n import _, _LI
from cinder import replication as replicationAPI
from cinder import volume

LOG = logging.getLogger(__name__)

authorize = extensions.soft_extension_authorizer('volume',
                                                 'volume_replication')


class VolumeReplicationController(wsgi.Controller):
    """The Volume Replication API controller for the Openstack API."""

    def __init__(self, *args, **kwargs):
        super(VolumeReplicationController, self).__init__(*args, **kwargs)
        self.volume_api = volume.API()
        self.replication_api = replicationAPI.API()

    def _add_replication_attributes(self, req, context, resp_volume):
        db_volume = req.cached_resource_by_id(resp_volume['id'])
        key = "%s:extended_status" % Volume_replication.alias
        resp_volume[key] = db_volume['replication_extended_status']
        key = "%s:driver_data" % Volume_replication.alias
        resp_volume[key] = db_volume['replication_driver_data']

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['cinder.context']
        if authorize(context):
            resp_obj.attach(xml=VolumeReplicationAttributeTemplate())
            self._add_replication_attributes(req, context,
                                             resp_obj.obj['volume'])

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['cinder.context']
        if authorize(context):
            resp_obj.attach(xml=VolumeReplicationListAttributeTemplate())
            for vol in list(resp_obj.obj['volumes']):
                self._add_replication_attributes(req, context, vol)

    @wsgi.response(202)
    @wsgi.action('os-promote-replica')
    def promote(self, req, id, body):
        context = req.environ['cinder.context']
        try:
            vol = self.volume_api.get(context, id)
            LOG.info(_LI('Attempting to promote secondary replica to primary'
                         ' for volume %s.'),
                     id,
                     context=context)
            self.replication_api.promote(context, vol)
        except exception.NotFound:
            msg = _("Volume could not be found")
            raise exc.HTTPNotFound(explanation=msg)
        except exception.ReplicationError as error:
            raise exc.HTTPBadRequest(explanation=six.text_type(error))
        return webob.Response(status_int=202)

    @wsgi.response(202)
    @wsgi.action('os-reenable-replica')
    def reenable(self, req, id, body):
        context = req.environ['cinder.context']
        try:
            vol = self.volume_api.get(context, id)
            LOG.info(_LI('Attempting to sync secondary replica with primary'
                         ' for volume %s.'),
                     id,
                     context=context)
            self.replication_api.reenable(context, vol)
        except exception.NotFound:
            msg = _("Volume could not be found")
            raise exc.HTTPNotFound(explanation=msg)
        except exception.ReplicationError as error:
            raise exc.HTTPBadRequest(explanation=six.text_type(error))
        return webob.Response(status_int=202)


class Volume_replication(extensions.ExtensionDescriptor):
    """Volume replication management support."""

    name = "VolumeReplication"
    alias = "os-volume-replication"
    namespace = "http://docs.openstack.org/volume/ext/volume_replication/" + \
                "api/v1"
    updated = "2014-08-01T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = VolumeReplicationController()
        extension = extensions.ControllerExtension(self, 'volumes', controller)
        return [extension]


def make_volume(elem):
    elem.set('{%s}extended_status' % Volume_replication.namespace,
             '%s:extended_status' % Volume_replication.alias)
    elem.set('{%s}driver_data' % Volume_replication.namespace,
             '%s:driver_data' % Volume_replication.alias)


class VolumeReplicationAttributeTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('volume', selector='volume')
        make_volume(root)
        alias = Volume_replication.alias
        namespace = Volume_replication.namespace
        return xmlutil.SlaveTemplate(root, 1, nsmap={alias: namespace})


class VolumeReplicationListAttributeTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('volumes')
        elem = xmlutil.SubTemplateElement(root, 'volume', selector='volumes')
        make_volume(elem)
        alias = Volume_replication.alias
        namespace = Volume_replication.namespace
        return xmlutil.SlaveTemplate(root, 1, nsmap={alias: namespace})
