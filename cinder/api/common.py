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


import os
import re
import urllib

from oslo_config import cfg
from oslo_log import log as logging
import six.moves.urllib.parse as urlparse
import webob

from cinder.api.openstack import wsgi
from cinder.api import xmlutil
from cinder.i18n import _
from cinder import utils


api_common_opts = [
    cfg.IntOpt('osapi_max_limit',
               default=1000,
               help='The maximum number of items that a collection '
                    'resource returns in a single response'),
    cfg.StrOpt('osapi_volume_base_URL',
               default=None,
               help='Base URL that will be presented to users in links '
                    'to the OpenStack Volume API',
               deprecated_name='osapi_compute_link_prefix'),
]

CONF = cfg.CONF
CONF.register_opts(api_common_opts)

LOG = logging.getLogger(__name__)


XML_NS_V1 = 'http://docs.openstack.org/api/openstack-block-storage/1.0/content'
XML_NS_V2 = 'http://docs.openstack.org/api/openstack-block-storage/2.0/content'


# Regex that matches alphanumeric characters, periods, hyphens,
# colons and underscores:
# ^ assert position at start of the string
# [\w\.\-\:\_] match expression
# $ assert position at end of the string
VALID_KEY_NAME_REGEX = re.compile(r"^[\w\.\-\:\_]+$", re.UNICODE)


def validate_key_names(key_names_list):
    """Validate each item of the list to match key name regex."""
    for key_name in key_names_list:
        if not VALID_KEY_NAME_REGEX.match(key_name):
            return False
    return True


def get_pagination_params(request):
    """Return marker, limit tuple from request.

    :param request: `wsgi.Request` possibly containing 'marker' and 'limit'
                    GET variables. 'marker' is the id of the last element
                    the client has seen, and 'limit' is the maximum number
                    of items to return. If 'limit' is not specified, 0, or
                    > max_limit, we default to max_limit. Negative values
                    for either marker or limit will cause
                    exc.HTTPBadRequest() exceptions to be raised.

    """
    params = {}
    if 'limit' in request.GET:
        params['limit'] = _get_limit_param(request)
    if 'marker' in request.GET:
        params['marker'] = _get_marker_param(request)
    return params


def _get_limit_param(request):
    """Extract integer limit from request or fail."""
    try:
        limit = int(request.GET['limit'])
    except ValueError:
        msg = _('limit param must be an integer')
        raise webob.exc.HTTPBadRequest(explanation=msg)
    if limit < 0:
        msg = _('limit param must be positive')
        raise webob.exc.HTTPBadRequest(explanation=msg)
    return limit


def _get_marker_param(request):
    """Extract marker id from request or fail."""
    return request.GET['marker']


def limited(items, request, max_limit=CONF.osapi_max_limit):
    """Return a slice of items according to requested offset and limit.

    :param items: A sliceable entity
    :param request: ``wsgi.Request`` possibly containing 'offset' and 'limit'
                    GET variables. 'offset' is where to start in the list,
                    and 'limit' is the maximum number of items to return. If
                    'limit' is not specified, 0, or > max_limit, we default
                    to max_limit. Negative values for either offset or limit
                    will cause exc.HTTPBadRequest() exceptions to be raised.
    :kwarg max_limit: The maximum number of items to return from 'items'
    """
    try:
        offset = int(request.GET.get('offset', 0))
    except ValueError:
        msg = _('offset param must be an integer')
        raise webob.exc.HTTPBadRequest(explanation=msg)

    try:
        limit = int(request.GET.get('limit', max_limit))
    except ValueError:
        msg = _('limit param must be an integer')
        raise webob.exc.HTTPBadRequest(explanation=msg)

    if limit < 0:
        msg = _('limit param must be positive')
        raise webob.exc.HTTPBadRequest(explanation=msg)

    if offset < 0:
        msg = _('offset param must be positive')
        raise webob.exc.HTTPBadRequest(explanation=msg)

    limit = min(max_limit, limit or max_limit)
    range_end = offset + limit
    return items[offset:range_end]


def limited_by_marker(items, request, max_limit=CONF.osapi_max_limit):
    """Return a slice of items according to the requested marker and limit."""
    params = get_pagination_params(request)

    limit = params.get('limit', max_limit)
    marker = params.get('marker')

    limit = min(max_limit, limit)
    start_index = 0
    if marker:
        start_index = -1
        for i, item in enumerate(items):
            if 'flavorid' in item:
                if item['flavorid'] == marker:
                    start_index = i + 1
                    break
            elif item['id'] == marker or item.get('uuid') == marker:
                start_index = i + 1
                break
        if start_index < 0:
            msg = _('marker [%s] not found') % marker
            raise webob.exc.HTTPBadRequest(explanation=msg)
    range_end = start_index + limit
    return items[start_index:range_end]


def get_sort_params(params, default_key='created_at', default_dir='desc'):
    """Retrieves sort keys/directions parameters.

    Processes the parameters to create a list of sort keys and sort directions
    that correspond to either the 'sort' parameter or the 'sort_key' and
    'sort_dir' parameter values. The value of the 'sort' parameter is a comma-
    separated list of sort keys, each key is optionally appended with
    ':<sort_direction>'.

    Note that the 'sort_key' and 'sort_dir' parameters are deprecated in kilo
    and an exception is raised if they are supplied with the 'sort' parameter.

    The sort parameters are removed from the request parameters by this
    function.

    :param params: webob.multidict of request parameters (from
                   cinder.api.openstack.wsgi.Request.params)
    :param default_key: default sort key value, added to the list if no
                        sort keys are supplied
    :param default_dir: default sort dir value, added to the list if the
                        corresponding key does not have a direction
                        specified
    :returns: list of sort keys, list of sort dirs
    :raise webob.exc.HTTPBadRequest: If both 'sort' and either 'sort_key' or
                                     'sort_dir' are supplied parameters
    """
    if 'sort' in params and ('sort_key' in params or 'sort_dir' in params):
        msg = _("The 'sort_key' and 'sort_dir' parameters are deprecated and "
                "cannot be used with the 'sort' parameter.")
        raise webob.exc.HTTPBadRequest(explanation=msg)
    sort_keys = []
    sort_dirs = []
    if 'sort' in params:
        for sort in params.pop('sort').strip().split(','):
            sort_key, _sep, sort_dir = sort.partition(':')
            if not sort_dir:
                sort_dir = default_dir
            sort_keys.append(sort_key.strip())
            sort_dirs.append(sort_dir.strip())
    else:
        sort_key = params.pop('sort_key', default_key)
        sort_dir = params.pop('sort_dir', default_dir)
        sort_keys.append(sort_key.strip())
        sort_dirs.append(sort_dir.strip())
    return sort_keys, sort_dirs


def remove_version_from_href(href):
    """Removes the first api version from the href.

    Given: 'http://www.cinder.com/v1.1/123'
    Returns: 'http://www.cinder.com/123'

    Given: 'http://www.cinder.com/v1.1'
    Returns: 'http://www.cinder.com'

    """
    parsed_url = urlparse.urlsplit(href)
    url_parts = parsed_url.path.split('/', 2)

    # NOTE: this should match vX.X or vX
    expression = re.compile(r'^v([0-9]+|[0-9]+\.[0-9]+)(/.*|$)')
    if expression.match(url_parts[1]):
        del url_parts[1]

    new_path = '/'.join(url_parts)

    if new_path == parsed_url.path:
        msg = 'href %s does not contain version' % href
        LOG.debug(msg)
        raise ValueError(msg)

    parsed_url = list(parsed_url)
    parsed_url[2] = new_path
    return urlparse.urlunsplit(parsed_url)


class ViewBuilder(object):
    """Model API responses as dictionaries."""

    _collection_name = None

    def _get_links(self, request, identifier):
        return [{"rel": "self",
                 "href": self._get_href_link(request, identifier), },
                {"rel": "bookmark",
                 "href": self._get_bookmark_link(request, identifier), }]

    def _get_next_link(self, request, identifier, collection_name):
        """Return href string with proper limit and marker params."""
        params = request.params.copy()
        params["marker"] = identifier
        prefix = self._update_link_prefix(request.application_url,
                                          CONF.osapi_volume_base_URL)
        url = os.path.join(prefix,
                           request.environ["cinder.context"].project_id,
                           collection_name)
        return "%s?%s" % (url, urllib.urlencode(params))

    def _get_href_link(self, request, identifier):
        """Return an href string pointing to this object."""
        prefix = self._update_link_prefix(request.application_url,
                                          CONF.osapi_volume_base_URL)
        return os.path.join(prefix,
                            request.environ["cinder.context"].project_id,
                            self._collection_name,
                            str(identifier))

    def _get_bookmark_link(self, request, identifier):
        """Create a URL that refers to a specific resource."""
        base_url = remove_version_from_href(request.application_url)
        base_url = self._update_link_prefix(base_url,
                                            CONF.osapi_volume_base_URL)
        return os.path.join(base_url,
                            request.environ["cinder.context"].project_id,
                            self._collection_name,
                            str(identifier))

    def _get_collection_links(self, request, items, collection_name,
                              item_count, id_key="uuid"):
        """Retrieve 'next' link, if applicable.

        The next link is included if:
        1) 'limit' param is specified and equal to or less than the
        number of items.
        2) 'limit' param is specified and both the limit and the number
        of items are greater than CONF.osapi_max_limit, even if limit
        is greater than the number of items.
        3) 'limit' param is NOT specified and the number of items is
        greater than CONF.osapi_max_limit.
        Notes: The case limit equals to 0 or CONF.osapi_max_limit equals to 0
        is not included in the above conditions.

        :param request: API request
        :param items: List of collection items
        :param collection_name: Name of collection, used to generate the
                                next link for a pagination query
        :param item_count: Length of the list of the original collection
                           items
        :param id_key: Attribute key used to retrieve the unique ID, used
                       to generate the next link marker for a pagination query
        :returns links
        """
        limit = request.params.get("limit", None)
        if limit is None or int(limit) > CONF.osapi_max_limit:
            # If limit is not set in the request or greater than
            # osapi_max_limit, len(items) < item_count means the items
            # are limited by osapi_max_limit and we need to generate the
            # next link. Otherwise, all the items will be returned in
            # the response, no next link is generated.
            if len(items) < item_count:
                return self._generate_next_link(items, id_key, request,
                                                collection_name)
        else:
            # If limit is set in the request and not more than
            # osapi_max_limit, int(limit) == len(items) means it is possible
            # that the DB still have more items left. In this case,
            # we generate the next link.
            limit = int(limit)
            if limit and limit == len(items):
                return self._generate_next_link(items, id_key, request,
                                                collection_name)
        return []

    def _generate_next_link(self, items, id_key, request,
                            collection_name):
        links = []
        last_item = items[-1]
        if id_key in last_item:
            last_item_id = last_item[id_key]
        else:
            last_item_id = last_item["id"]
        links.append({
            "rel": "next",
            "href": self._get_next_link(request, last_item_id,
                                        collection_name),
        })
        return links

    def _update_link_prefix(self, orig_url, prefix):
        if not prefix:
            return orig_url
        url_parts = list(urlparse.urlsplit(orig_url))
        prefix_parts = list(urlparse.urlsplit(prefix))
        url_parts[0:2] = prefix_parts[0:2]
        return urlparse.urlunsplit(url_parts)


class MetadataDeserializer(wsgi.MetadataXMLDeserializer):
    def deserialize(self, text):
        dom = utils.safe_minidom_parse_string(text)
        metadata_node = self.find_first_child_named(dom, "metadata")
        metadata = self.extract_metadata(metadata_node)
        return {'body': {'metadata': metadata}}


class MetaItemDeserializer(wsgi.MetadataXMLDeserializer):
    def deserialize(self, text):
        dom = utils.safe_minidom_parse_string(text)
        metadata_item = self.extract_metadata(dom)
        return {'body': {'meta': metadata_item}}


class MetadataXMLDeserializer(wsgi.XMLDeserializer):

    def extract_metadata(self, metadata_node):
        """Marshal the metadata attribute of a parsed request."""
        if metadata_node is None:
            return {}
        metadata = {}
        for meta_node in self.find_children_named(metadata_node, "meta"):
            key = meta_node.getAttribute("key")
            metadata[key] = self.extract_text(meta_node)
        return metadata

    def _extract_metadata_container(self, datastring):
        dom = utils.safe_minidom_parse_string(datastring)
        metadata_node = self.find_first_child_named(dom, "metadata")
        metadata = self.extract_metadata(metadata_node)
        return {'body': {'metadata': metadata}}

    def create(self, datastring):
        return self._extract_metadata_container(datastring)

    def update_all(self, datastring):
        return self._extract_metadata_container(datastring)

    def update(self, datastring):
        dom = utils.safe_minidom_parse_string(datastring)
        metadata_item = self.extract_metadata(dom)
        return {'body': {'meta': metadata_item}}


metadata_nsmap = {None: xmlutil.XMLNS_V11}


class MetaItemTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        sel = xmlutil.Selector('meta', xmlutil.get_items, 0)
        root = xmlutil.TemplateElement('meta', selector=sel)
        root.set('key', 0)
        root.text = 1
        return xmlutil.MasterTemplate(root, 1, nsmap=metadata_nsmap)


class MetadataTemplateElement(xmlutil.TemplateElement):
    def will_render(self, datum):
        return True


class MetadataTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = MetadataTemplateElement('metadata', selector='metadata')
        elem = xmlutil.SubTemplateElement(root, 'meta',
                                          selector=xmlutil.get_items)
        elem.set('key', 0)
        elem.text = 1
        return xmlutil.MasterTemplate(root, 1, nsmap=metadata_nsmap)
