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


import json
import os
import re

import enum
from oslo_config import cfg
from oslo_log import log as logging
from six.moves import urllib
import webob

from cinder.api import microversions as mv
from cinder.common import constants
from cinder import exception
from cinder.i18n import _
from cinder import utils


api_common_opts = [
    cfg.IntOpt('osapi_max_limit',
               default=1000,
               help='The maximum number of items that a collection '
                    'resource returns in a single response'),
    cfg.StrOpt('resource_query_filters_file',
               default='/etc/cinder/resource_filters.json',
               help="Json file indicating user visible filter "
                    "parameters for list queries."),
]

CONF = cfg.CONF
CONF.import_opt('public_endpoint', 'cinder.api.views.versions')
CONF.register_opts(api_common_opts)

LOG = logging.getLogger(__name__)
_FILTERS_COLLECTION = None

ATTRIBUTE_CONVERTERS = {'name~': 'display_name~',
                        'description~': 'display_description~'}


METADATA_TYPES = enum.Enum('METADATA_TYPES', 'user image')


def get_pagination_params(params, max_limit=None):
    """Return marker, limit, offset tuple from request.

    :param params: `wsgi.Request`'s GET dictionary, possibly containing
                   'marker',  'limit', and 'offset' variables. 'marker' is the
                   id of the last element the client has seen, 'limit' is the
                   maximum number of items to return and 'offset' is the number
                   of items to skip from the marker or from the first element.
                   If 'limit' is not specified, or > max_limit, we default to
                   max_limit. Negative values for either offset or limit will
                   cause exc.HTTPBadRequest() exceptions to be raised. If no
                   offset is present we'll default to 0 and if no marker is
                   present we'll default to None.
    :max_limit: Max value 'limit' return value can take
    :returns: Tuple (marker, limit, offset)
    """
    max_limit = max_limit or CONF.osapi_max_limit
    limit = _get_limit_param(params, max_limit)
    marker = _get_marker_param(params)
    offset = _get_offset_param(params)
    return marker, limit, offset


def _get_limit_param(params, max_limit=None):
    """Extract integer limit from request's dictionary or fail.

   Defaults to max_limit if not present and returns max_limit if present
   'limit' is greater than max_limit.
    """
    max_limit = max_limit or CONF.osapi_max_limit
    try:
        limit = int(params.pop('limit', max_limit))
    except ValueError:
        msg = _('limit param must be an integer')
        raise webob.exc.HTTPBadRequest(explanation=msg)
    if limit < 0:
        msg = _('limit param must be positive')
        raise webob.exc.HTTPBadRequest(explanation=msg)
    limit = min(limit, max_limit)
    return limit


def _get_marker_param(params):
    """Extract marker id from request's dictionary (defaults to None)."""
    return params.pop('marker', None)


def _get_offset_param(params):
    """Extract offset id from request's dictionary (defaults to 0) or fail."""
    offset = params.pop('offset', 0)
    return utils.validate_integer(offset, 'offset', 0, constants.DB_MAX_INT)


def limited(items, request, max_limit=None):
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
    max_limit = max_limit or CONF.osapi_max_limit
    marker, limit, offset = get_pagination_params(request.GET.copy(),
                                                  max_limit)
    range_end = offset + (limit or max_limit)
    return items[offset:range_end]


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


def get_request_url(request):
    url = request.application_url
    headers = request.headers
    forwarded = headers.get('X-Forwarded-Host')
    if forwarded:
        url_parts = list(urllib.parse.urlsplit(url))
        url_parts[1] = re.split(r',\s?', forwarded)[-1]
        url = urllib.parse.urlunsplit(url_parts).rstrip('/')
    return url


def remove_version_from_href(href):
    """Removes the first API version from the href.

    Given: 'http://cinder.example.com/v1.1/123'
    Returns: 'http://cinder.example.com/123'

    Given: 'http://cinder.example.com/v1.1'
    Returns: 'http://cinder.example.com'

    Given: 'http://cinder.example.com/volume/drivers/v1.1/flashsystem'
    Returns: 'http://cinder.example.com/volume/drivers/flashsystem'

    """
    parsed_url = urllib.parse.urlsplit(href)
    url_parts = parsed_url.path.split('/', 2)

    # NOTE: this should match vX.X or vX
    expression = re.compile(r'^v([0-9]+|[0-9]+\.[0-9]+)(/.*|$)')
    for x in range(len(url_parts)):
        if expression.match(url_parts[x]):
            del url_parts[x]
            break

    new_path = '/'.join(url_parts)

    if new_path == parsed_url.path:
        msg = 'href %s does not contain version' % href
        LOG.debug(msg)
        raise ValueError(msg)

    parsed_url = list(parsed_url)
    parsed_url[2] = new_path
    return urllib.parse.urlunsplit(parsed_url)


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
        prefix = self._update_link_prefix(get_request_url(request),
                                          CONF.public_endpoint)
        url = os.path.join(prefix,
                           request.environ["cinder.context"].project_id,
                           collection_name)
        return "%s?%s" % (url, urllib.parse.urlencode(params))

    def _get_href_link(self, request, identifier):
        """Return an href string pointing to this object."""
        prefix = self._update_link_prefix(get_request_url(request),
                                          CONF.public_endpoint)
        return os.path.join(prefix,
                            request.environ["cinder.context"].project_id,
                            self._collection_name,
                            str(identifier))

    def _get_bookmark_link(self, request, identifier):
        """Create a URL that refers to a specific resource."""
        base_url = remove_version_from_href(get_request_url(request))
        base_url = self._update_link_prefix(base_url,
                                            CONF.public_endpoint)
        return os.path.join(base_url,
                            request.environ["cinder.context"].project_id,
                            self._collection_name,
                            str(identifier))

    def _get_collection_links(self, request, items, collection_name,
                              item_count=None, id_key="uuid"):
        """Retrieve 'next' link, if applicable.

        The next link is included if we are returning as many items as we can,
        given the restrictions of limit optional request parameter and
        osapi_max_limit configuration parameter as long as we are returning
        some elements.

        So we return next link if:

        1) 'limit' param is specified and equal to the number of items.
        2) 'limit' param is NOT specified and the number of items is
           equal to CONF.osapi_max_limit.

        :param request: API request
        :param items: List of collection items
        :param collection_name: Name of collection, used to generate the
                                next link for a pagination query
        :param item_count: Length of the list of the original collection
                           items
        :param id_key: Attribute key used to retrieve the unique ID, used
                       to generate the next link marker for a pagination query
        :returns: links
        """
        item_count = item_count or len(items)
        limit = _get_limit_param(request.GET.copy())
        if len(items) and limit <= item_count:
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
        url_parts = list(urllib.parse.urlsplit(orig_url))
        prefix_parts = list(urllib.parse.urlsplit(prefix))
        url_parts[0:2] = prefix_parts[0:2]
        url_parts[2] = prefix_parts[2] + url_parts[2]

        return urllib.parse.urlunsplit(url_parts).rstrip('/')


def get_cluster_host(req, params, cluster_version=None):
    """Get cluster and host from the parameters.

    This method checks the presence of cluster and host parameters and returns
    them depending on the cluster_version.

    If cluster_version is False we will never return the cluster_name and we
    will require the presence of the host parameter.

    If cluster_version is None we will always check for the presence of the
    cluster parameter, and if cluster_version is a string with a version we
    will only check for the presence of the parameter if the version of the
    request is not less than  it.  In both cases we will require one and only
    one parameter, host or cluster.
    """
    if (cluster_version is not False and
            req.api_version_request.matches(cluster_version)):
        cluster_name = params.get('cluster')
        msg = _('One and only one of cluster and host must be set.')
    else:
        cluster_name = None
        msg = _('Host field is missing.')

    host = params.get('host')
    if bool(cluster_name) == bool(host):
        raise exception.InvalidInput(reason=msg)
    return cluster_name, host


def _initialize_filters():
    global _FILTERS_COLLECTION
    if not _FILTERS_COLLECTION:
        with open(CONF.resource_query_filters_file, 'r') as filters_file:
            _FILTERS_COLLECTION = json.load(filters_file)


def get_enabled_resource_filters(resource=None):
    """Get list of configured/allowed filters for the specified resource.

    This method checks resource_query_filters_file and returns dictionary
    which contains the specified resource and its allowed filters:

    .. code-block:: json

            {
                "resource": ["filter1", "filter2", "filter3"]
            }

    if resource is not specified, all of the configuration will be returned,
    and if the resource is not found, empty dict will be returned.
    """
    try:
        _initialize_filters()
        if not resource:
            return _FILTERS_COLLECTION
        else:
            return {resource: _FILTERS_COLLECTION[resource]}
    except Exception:
        LOG.debug("Failed to collect resource %s's filters.", resource)
        return {}


def convert_filter_attributes(filters, resource):
    for key in filters.copy().keys():
        if resource in ['volume', 'backup',
                        'snapshot'] and key in ATTRIBUTE_CONVERTERS.keys():
            filters[ATTRIBUTE_CONVERTERS[key]] = filters[key]
            filters.pop(key)


def reject_invalid_filters(context, filters, resource,
                           enable_like_filter=False):
    invalid_filters = []
    for key in filters.copy().keys():
        try:
            # Only ASCII characters can be valid filter keys,
            # in PY2/3, the key can be either unicode or string.
            if isinstance(key, str):
                key.encode('ascii')
            else:
                key.decode('ascii')
        except (UnicodeEncodeError, UnicodeDecodeError):
            raise webob.exc.HTTPBadRequest(
                explanation=_('Filter keys can only contain '
                              'ASCII characters.'))

    if context.is_admin and resource not in ['pool']:
        # Allow all options except resource is pool
        # pool API is only available for admin
        return
    # Check the configured filters against those passed in resource
    configured_filters = get_enabled_resource_filters(resource)
    if configured_filters:
        configured_filters = configured_filters[resource]
    else:
        configured_filters = []
    for key in filters.copy().keys():
        if not enable_like_filter:
            if key not in configured_filters:
                invalid_filters.append(key)
        else:
            # If 'key~' is configured, both 'key' and 'key~' are valid.
            if not (key in configured_filters or
                    "%s~" % key in configured_filters):
                invalid_filters.append(key)
    if invalid_filters:
        if 'all_tenants' in invalid_filters:
            invalid_filters.remove('all_tenants')
        if len(invalid_filters) == 0:
            return
        raise webob.exc.HTTPBadRequest(
            explanation=_('Invalid filters %s are found in query '
                          'options.') % ','.join(invalid_filters))


def process_general_filtering(resource):
    def wrapper(process_non_general_filtering):
        def _decorator(*args, **kwargs):
            req_version = kwargs.get('req_version')
            filters = kwargs.get('filters')
            context = kwargs.get('context')
            if req_version.matches(mv.RESOURCE_FILTER):
                support_like = False
                if req_version.matches(mv.LIKE_FILTER):
                    support_like = True
                reject_invalid_filters(context, filters,
                                       resource, support_like)
                convert_filter_attributes(filters, resource)

            else:
                process_non_general_filtering(*args, **kwargs)
        return _decorator
    return wrapper
