# Copyright 2010 OpenStack Foundation
# Copyright 2015 Clinton Knight
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


import copy
import datetime

from lxml import etree
from oslo_config import cfg

from cinder.api import extensions
from cinder.api import openstack
from cinder.api.openstack import api_version_request
from cinder.api.openstack import wsgi
from cinder.api.views import versions as views_versions
from cinder.api import xmlutil


CONF = cfg.CONF

_LINKS = [{
    "rel": "describedby",
    "type": "text/html",
    "href": "http://docs.openstack.org/",
}]

_MEDIA_TYPES = [{
    "base":
    "application/json",
    "type":
    "application/vnd.openstack.volume+json;version=1",
},
    {"base":
     "application/xml",
     "type":
     "application/vnd.openstack.volume+xml;version=1",
     },
]

_KNOWN_VERSIONS = {
    "v1.0": {
        "id": "v1.0",
        "status": "DEPRECATED",
        "version": "",
        "min_version": "",
        "updated": "2016-05-02T20:25:19Z",
        "links": _LINKS,
        "media-types": _MEDIA_TYPES,
    },
    "v2.0": {
        "id": "v2.0",
        "status": "SUPPORTED",
        "version": "",
        "min_version": "",
        "updated": "2014-06-28T12:20:21Z",
        "links": _LINKS,
        "media-types": _MEDIA_TYPES,
    },
    "v3.0": {
        "id": "v3.0",
        "status": "CURRENT",
        "version": api_version_request._MAX_API_VERSION,
        "min_version": api_version_request._MIN_API_VERSION,
        "updated": "2016-02-08T12:20:21Z",
        "links": _LINKS,
        "media-types": _MEDIA_TYPES,
    },
}


class Versions(openstack.APIRouter):
    """Route versions requests."""

    ExtensionManager = extensions.ExtensionManager

    def _setup_routes(self, mapper, ext_mgr):
        self.resources['versions'] = create_resource()
        mapper.connect('versions', '/',
                       controller=self.resources['versions'],
                       action='all')
        mapper.redirect('', '/')


class VersionsController(wsgi.Controller):

    def __init__(self):
        super(VersionsController, self).__init__(None)

    @wsgi.Controller.api_version('1.0')
    def index(self, req):  # pylint: disable=E0102
        """Return versions supported prior to the microversions epoch."""
        builder = views_versions.get_view_builder(req)
        known_versions = copy.deepcopy(_KNOWN_VERSIONS)
        known_versions.pop('v2.0')
        known_versions.pop('v3.0')
        return builder.build_versions(known_versions)

    @wsgi.Controller.api_version('2.0')  # noqa
    def index(self, req):  # pylint: disable=E0102
        """Return versions supported prior to the microversions epoch."""
        builder = views_versions.get_view_builder(req)
        known_versions = copy.deepcopy(_KNOWN_VERSIONS)
        known_versions.pop('v1.0')
        known_versions.pop('v3.0')
        return builder.build_versions(known_versions)

    @wsgi.Controller.api_version('3.0')  # noqa
    def index(self, req):  # pylint: disable=E0102
        """Return versions supported after the start of microversions."""
        builder = views_versions.get_view_builder(req)
        known_versions = copy.deepcopy(_KNOWN_VERSIONS)
        known_versions.pop('v1.0')
        known_versions.pop('v2.0')
        return builder.build_versions(known_versions)

    # NOTE (cknight): Calling the versions API without
    # /v1, /v2, or /v3 in the URL will lead to this unversioned
    # method, which should always return info about all
    # available versions.
    @wsgi.response(300)
    def all(self, req):
        """Return all known versions."""
        builder = views_versions.get_view_builder(req)
        known_versions = copy.deepcopy(_KNOWN_VERSIONS)
        return builder.build_versions(known_versions)


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


def create_resource():
    return wsgi.Resource(VersionsController())
