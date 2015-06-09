# Copyright 2010 OpenStack Foundation
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


import datetime

from lxml import etree
from oslo_config import cfg

from cinder.api.openstack import wsgi
from cinder.api.views import versions as views_versions
from cinder.api import xmlutil


CONF = cfg.CONF


_KNOWN_VERSIONS = {
    "v2.0": {
        "id": "v2.0",
        "status": "CURRENT",
        "updated": "2012-11-21T11:33:21Z",
        "links": [
            {
                "rel": "describedby",
                "type": "text/html",
                "href": "http://docs.openstack.org/",
            },
        ],
        "media-types": [
            {
                "base": "application/xml",
                "type": "application/vnd.openstack.volume+xml;version=1",
            },
            {
                "base": "application/json",
                "type": "application/vnd.openstack.volume+json;version=1",
            }
        ],
    },
    "v1.0": {
        "id": "v1.0",
        "status": "SUPPORTED",
        "updated": "2014-06-28T12:20:21Z",
        "links": [
            {
                "rel": "describedby",
                "type": "text/html",
                "href": "http://docs.openstack.org/",
            },
        ],
        "media-types": [
            {
                "base": "application/xml",
                "type": "application/vnd.openstack.volume+xml;version=1",
            },
            {
                "base": "application/json",
                "type": "application/vnd.openstack.volume+json;version=1",
            }
        ],
    }
}


def get_supported_versions():
    versions = {}

    if CONF.enable_v1_api:
        versions['v1.0'] = _KNOWN_VERSIONS['v1.0']
    if CONF.enable_v2_api:
        versions['v2.0'] = _KNOWN_VERSIONS['v2.0']

    return versions


class MediaTypesTemplateElement(xmlutil.TemplateElement):
    def will_render(self, datum):
        return 'media-types' in datum


def make_version(elem):
    elem.set('id')
    elem.set('status')
    elem.set('updated')

    mts = MediaTypesTemplateElement('media-types')
    elem.append(mts)

    mt = xmlutil.SubTemplateElement(mts, 'media-type', selector='media-types')
    mt.set('base')
    mt.set('type')

    xmlutil.make_links(elem, 'links')


version_nsmap = {None: xmlutil.XMLNS_COMMON_V10, 'atom': xmlutil.XMLNS_ATOM}


class VersionTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('version', selector='version')
        make_version(root)
        return xmlutil.MasterTemplate(root, 1, nsmap=version_nsmap)


class VersionsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('versions')
        elem = xmlutil.SubTemplateElement(root, 'version', selector='versions')
        make_version(elem)
        return xmlutil.MasterTemplate(root, 1, nsmap=version_nsmap)


class ChoicesTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('choices')
        elem = xmlutil.SubTemplateElement(root, 'version', selector='choices')
        make_version(elem)
        return xmlutil.MasterTemplate(root, 1, nsmap=version_nsmap)


class AtomSerializer(wsgi.XMLDictSerializer):

    NSMAP = {None: xmlutil.XMLNS_ATOM}

    def __init__(self, metadata=None, xmlns=None):
        self.metadata = metadata or {}
        if not xmlns:
            self.xmlns = wsgi.XML_NS_ATOM
        else:
            self.xmlns = xmlns

    def _get_most_recent_update(self, versions):
        recent = None
        for version in versions:
            updated = datetime.datetime.strptime(version['updated'],
                                                 '%Y-%m-%dT%H:%M:%SZ')
            if not recent:
                recent = updated
            elif updated > recent:
                recent = updated

        return recent.strftime('%Y-%m-%dT%H:%M:%SZ')

    def _get_base_url(self, link_href):
        # Make sure no trailing /
        link_href = link_href.rstrip('/')
        return link_href.rsplit('/', 1)[0] + '/'

    def _create_feed(self, versions, feed_title, feed_id):
        feed = etree.Element('feed', nsmap=self.NSMAP)
        title = etree.SubElement(feed, 'title')
        title.set('type', 'text')
        title.text = feed_title

        # Set this updated to the most recently updated version
        recent = self._get_most_recent_update(versions)
        etree.SubElement(feed, 'updated').text = recent

        etree.SubElement(feed, 'id').text = feed_id

        link = etree.SubElement(feed, 'link')
        link.set('rel', 'self')
        link.set('href', feed_id)

        author = etree.SubElement(feed, 'author')
        etree.SubElement(author, 'name').text = 'Rackspace'
        etree.SubElement(author, 'uri').text = 'http://www.rackspace.com/'

        for version in versions:
            feed.append(self._create_version_entry(version))

        return feed

    def _create_version_entry(self, version):
        entry = etree.Element('entry')
        etree.SubElement(entry, 'id').text = version['links'][0]['href']
        title = etree.SubElement(entry, 'title')
        title.set('type', 'text')
        title.text = 'Version %s' % version['id']
        etree.SubElement(entry, 'updated').text = version['updated']

        for link in version['links']:
            link_elem = etree.SubElement(entry, 'link')
            link_elem.set('rel', link['rel'])
            link_elem.set('href', link['href'])
            if 'type' in link:
                link_elem.set('type', link['type'])

        content = etree.SubElement(entry, 'content')
        content.set('type', 'text')
        content.text = 'Version %s %s (%s)' % (version['id'],
                                               version['status'],
                                               version['updated'])
        return entry


class VersionsAtomSerializer(AtomSerializer):
    def default(self, data):
        versions = data['versions']
        feed_id = self._get_base_url(versions[0]['links'][0]['href'])
        feed = self._create_feed(versions, 'Available API Versions', feed_id)
        return self._to_xml(feed)


class VersionAtomSerializer(AtomSerializer):
    def default(self, data):
        version = data['version']
        feed_id = version['links'][0]['href']
        feed = self._create_feed([version], 'About This Version', feed_id)
        return self._to_xml(feed)


class Versions(wsgi.Resource):

    def __init__(self):
        super(Versions, self).__init__(None)

    @wsgi.serializers(xml=VersionsTemplate,
                      atom=VersionsAtomSerializer)
    def index(self, req):
        """Return all versions."""
        builder = views_versions.get_view_builder(req)
        return builder.build_versions(get_supported_versions())

    @wsgi.serializers(xml=ChoicesTemplate)
    @wsgi.response(300)
    def multi(self, req):
        """Return multiple choices."""
        builder = views_versions.get_view_builder(req)
        return builder.build_choices(get_supported_versions(), req)

    def get_action_args(self, request_environment):
        """Parse dictionary created by routes library."""
        args = {}
        if request_environment['PATH_INFO'] == '/':
            args['action'] = 'index'
        else:
            args['action'] = 'multi'

        return args


class VolumeVersion(object):
    @wsgi.serializers(xml=VersionTemplate,
                      atom=VersionAtomSerializer)
    def show(self, req):
        builder = views_versions.get_view_builder(req)
        if 'v1' in builder.base_url:
            return builder.build_version(_KNOWN_VERSIONS['v1.0'])
        else:
            return builder.build_version(_KNOWN_VERSIONS['v2.0'])


def create_resource():
    return wsgi.Resource(VolumeVersion())
