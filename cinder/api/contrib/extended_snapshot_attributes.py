#   Copyright 2012 OpenStack Foundation
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.

"""The Extended Snapshot Attributes API extension."""

from oslo_log import log as logging

from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.api import xmlutil


LOG = logging.getLogger(__name__)
authorize = extensions.soft_extension_authorizer(
    'volume',
    'extended_snapshot_attributes')


class ExtendedSnapshotAttributesController(wsgi.Controller):
    def _extend_snapshot(self, req, resp_snap):
        db_snap = req.get_db_snapshot(resp_snap['id'])
        for attr in ['project_id', 'progress']:
            key = "%s:%s" % (Extended_snapshot_attributes.alias, attr)
            resp_snap[key] = db_snap[attr]

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['cinder.context']
        if authorize(context):
            # Attach our slave template to the response object
            resp_obj.attach(xml=ExtendedSnapshotAttributeTemplate())
            snapshot = resp_obj.obj['snapshot']
            self._extend_snapshot(req, snapshot)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['cinder.context']
        if authorize(context):
            # Attach our slave template to the response object
            resp_obj.attach(xml=ExtendedSnapshotAttributesTemplate())
            for snapshot in list(resp_obj.obj['snapshots']):
                self._extend_snapshot(req, snapshot)


class Extended_snapshot_attributes(extensions.ExtensionDescriptor):
    """Extended SnapshotAttributes support."""

    name = "ExtendedSnapshotAttributes"
    alias = "os-extended-snapshot-attributes"
    namespace = ("http://docs.openstack.org/volume/ext/"
                 "extended_snapshot_attributes/api/v1")
    updated = "2012-06-19T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = ExtendedSnapshotAttributesController()
        extension = extensions.ControllerExtension(self, 'snapshots',
                                                   controller)
        return [extension]


def make_snapshot(elem):
    elem.set('{%s}project_id' % Extended_snapshot_attributes.namespace,
             '%s:project_id' % Extended_snapshot_attributes.alias)
    elem.set('{%s}progress' % Extended_snapshot_attributes.namespace,
             '%s:progress' % Extended_snapshot_attributes.alias)


class ExtendedSnapshotAttributeTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('snapshot', selector='snapshot')
        make_snapshot(root)
        alias = Extended_snapshot_attributes.alias
        namespace = Extended_snapshot_attributes.namespace
        return xmlutil.SlaveTemplate(root, 1, nsmap={alias: namespace})


class ExtendedSnapshotAttributesTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('snapshots')
        elem = xmlutil.SubTemplateElement(root, 'snapshot',
                                          selector='snapshots')
        make_snapshot(elem)
        alias = Extended_snapshot_attributes.alias
        namespace = Extended_snapshot_attributes.namespace
        return xmlutil.SlaveTemplate(root, 1, nsmap={alias: namespace})
