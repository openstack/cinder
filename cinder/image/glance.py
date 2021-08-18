# Copyright 2010 OpenStack Foundation
# Copyright 2013 NTT corp.
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

"""Implementation of an image service that uses Glance as the backend"""

import copy
import itertools
import random
import shutil
import sys
import textwrap
import time
import typing
from typing import Any, Dict, Tuple  # noqa: H301
import urllib
import urllib.parse

import glanceclient.exc
from keystoneauth1.loading import session as ks_session
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import timeutils

from cinder import context
from cinder import exception
from cinder.i18n import _
from cinder import service_auth


image_opts = [
    cfg.ListOpt('allowed_direct_url_schemes',
                default=[],
                help='A list of url schemes that can be downloaded directly '
                     'via the direct_url.  Currently supported schemes: '
                     '[file, cinder].'),
    cfg.StrOpt('verify_glance_signatures',
               choices=['disabled', 'enabled'],
               default='enabled',
               help=textwrap.dedent(
                   """
                   Enable image signature verification.

                   Cinder uses the image signature metadata from Glance and
                   verifies the signature of a signed image while downloading
                   that image. There are two options here.

                   1. ``enabled``: verify when image has signature metadata.
                   2. ``disabled``: verification is turned off.

                   If the image signature cannot be verified or if the image
                   signature metadata is incomplete when required, then Cinder
                   will not create the volume and update it into an error
                   state. This provides end users with stronger assurances
                   of the integrity of the image data they are using to
                   create volumes.
                   """)),
    cfg.StrOpt('glance_catalog_info',
               default='image:glance:publicURL',
               help='Info to match when looking for glance in the service '
                    'catalog. Format is: separated values of the form: '
                    '<service_type>:<service_name>:<endpoint_type> - '
                    'Only used if glance_api_servers are not provided.'),
]
glance_core_properties_opts = [
    cfg.ListOpt('glance_core_properties',
                default=['checksum', 'container_format',
                         'disk_format', 'image_name', 'image_id',
                         'min_disk', 'min_ram', 'name', 'size'],
                help='Default core properties of image')
]
CONF = cfg.CONF
CONF.register_opts(image_opts)
CONF.register_opts(glance_core_properties_opts)

_SESSION = None

LOG = logging.getLogger(__name__)


def _parse_image_ref(image_href):
    """Parse an image href into composite parts.

    :param image_href: href of an image
    :returns: a tuple of the form (image_id, netloc, use_ssl)
    :raises ValueError:

    """
    url = urllib.parse.urlparse(image_href)
    netloc = url.netloc
    image_id = url.path.split('/')[-1]
    use_ssl = (url.scheme == 'https')
    return (image_id, netloc, use_ssl)


def _create_glance_client(context, netloc, use_ssl):
    """Instantiate a new glanceclient.Client object."""
    params = {'global_request_id': context.global_id}

    if use_ssl and CONF.auth_strategy == 'noauth':
        params = {'insecure': CONF.glance_api_insecure,
                  'cacert': CONF.glance_ca_certificates_file,
                  'timeout': CONF.glance_request_timeout,
                  'split_loggers': CONF.split_loggers
                  }
    if CONF.auth_strategy == 'keystone':
        global _SESSION
        if not _SESSION:
            config_options = {'insecure': CONF.glance_api_insecure,
                              'cacert': CONF.glance_ca_certificates_file,
                              'timeout': CONF.glance_request_timeout,
                              'cert': CONF.glance_certfile,
                              'key': CONF.glance_keyfile,
                              'split_loggers': CONF.split_loggers
                              }
            _SESSION = ks_session.Session().load_from_options(**config_options)

        auth = service_auth.get_auth_plugin(context)
        params['auth'] = auth
        params['session'] = _SESSION

    scheme = 'https' if use_ssl else 'http'
    endpoint = '%s://%s' % (scheme, netloc)
    return glanceclient.Client('2', endpoint, **params)


def get_api_servers(context):
    """Return Iterable over shuffled api servers.

    Shuffle a list of glance_api_servers and return an iterator
    that will cycle through the list, looping around to the beginning
    if necessary. If CONF.glance_api_servers is None then they will
    be retrieved from the catalog.
    """
    api_servers = []
    api_servers_info = []

    if CONF.glance_api_servers is None:
        info = CONF.glance_catalog_info
        try:
            service_type, service_name, endpoint_type = info.split(':')
        except ValueError:
            raise exception.InvalidConfigurationValue(_(
                "Failed to parse the configuration option "
                "'glance_catalog_info', must be in the form "
                "<service_type>:<service_name>:<endpoint_type>"))
        for entry in context.service_catalog:
            if entry.get('type') == service_type:
                api_servers.append(
                    entry.get('endpoints')[0].get(endpoint_type))
    else:
        for api_server in CONF.glance_api_servers:
            api_servers.append(api_server)

    for api_server in api_servers:
        if '//' not in api_server:
            api_server = 'http://' + api_server
        url = urllib.parse.urlparse(api_server)
        netloc = url.netloc + url.path
        use_ssl = (url.scheme == 'https')
        api_servers_info.append((netloc, use_ssl))

    random.shuffle(api_servers_info)
    return itertools.cycle(api_servers_info)


class GlanceClientWrapper(object):
    """Glance client wrapper class that implements retries."""

    def __init__(self, context=None, netloc=None, use_ssl=False):
        if netloc is not None:
            self.client = self._create_static_client(context,
                                                     netloc,
                                                     use_ssl)
        else:
            self.client = None
        self.api_servers = None

    def _create_static_client(self, context, netloc, use_ssl):
        """Create a client that we'll use for every call."""
        self.netloc = netloc
        self.use_ssl = use_ssl
        return _create_glance_client(context,
                                     self.netloc,
                                     self.use_ssl)

    def _create_onetime_client(self, context):
        """Create a client that will be used for one call."""
        if self.api_servers is None:
            self.api_servers = get_api_servers(context)
        self.netloc, self.use_ssl = next(self.api_servers)
        return _create_glance_client(context,
                                     self.netloc,
                                     self.use_ssl)

    def call(self, context, method, *args, **kwargs):
        """Call a glance client method.

        If we get a connection error,
        retry the request according to CONF.glance_num_retries.
        """

        retry_excs = (glanceclient.exc.ServiceUnavailable,
                      glanceclient.exc.InvalidEndpoint,
                      glanceclient.exc.CommunicationError)
        num_attempts = 1 + CONF.glance_num_retries
        glance_controller = kwargs.pop('controller', 'images')
        store_id = kwargs.pop('store_id', None)
        base_image_ref = kwargs.pop('base_image_ref', None)

        for attempt in range(1, num_attempts + 1):
            client = self.client or self._create_onetime_client(context)

            keys = ('x-image-meta-store', 'x-openstack-base-image-ref',)
            values = (store_id, base_image_ref,)

            headers = {k: v for (k, v) in zip(keys, values) if v is not None}
            if headers:
                client.http_client.additional_headers = headers

            try:
                controller = getattr(client, glance_controller)
                return getattr(controller, method)(*args, **kwargs)
            except retry_excs as e:
                netloc = self.netloc
                extra = "retrying"
                error_msg = _("Error contacting glance server "
                              "'%(netloc)s' for '%(method)s', "
                              "%(extra)s.")
                if attempt == num_attempts:
                    extra = 'done trying'
                    LOG.exception(error_msg, {'netloc': netloc,
                                              'method': method,
                                              'extra': extra})
                    raise exception.GlanceConnectionFailed(reason=e)

                LOG.exception(error_msg, {'netloc': netloc,
                                          'method': method,
                                          'extra': extra})
                time.sleep(1)
            except glanceclient.exc.HTTPOverLimit as e:
                raise exception.ImageLimitExceeded(e)


class GlanceImageService(object):
    """Provides storage and retrieval of disk image objects within Glance."""

    def __init__(self, client=None):
        self._client = client or GlanceClientWrapper()
        self._image_schema = None
        self.temp_images = None

    def detail(self, context, **kwargs):
        """Calls out to Glance for a list of detailed image information."""
        params = self._extract_query_params(kwargs)
        try:
            images = self._client.call(context, 'list', **params)
        except Exception:
            _reraise_translated_exception()

        _images = []
        for image in images:
            if self._is_image_available(context, image):
                _images.append(self._translate_from_glance(context, image))

        return _images

    def _extract_query_params(self, params):
        _params = {}
        accepted_params = ('filters', 'marker', 'limit',
                           'sort_key', 'sort_dir')
        for param in accepted_params:
            if param in params:
                _params[param] = params.get(param)

        return _params

    def list_members(self, context, image_id):
        """Returns a list of dicts with image member data."""
        try:
            return self._client.call(context,
                                     'list',
                                     controller='image_members',
                                     image_id=image_id)
        except Exception:
            _reraise_translated_image_exception(image_id)

    def get_stores(self, context):
        """Returns a list of dicts with stores information."""
        try:
            return self._client.call(context,
                                     'get_stores_info')
        except Exception:
            _reraise_translated_exception()

    def show(self,
             context: context.RequestContext,
             image_id: str) -> Dict[str, Any]:
        """Returns a dict with image data for the given opaque image id."""
        try:
            image = self._client.call(context, 'get', image_id)
        except Exception:
            _reraise_translated_image_exception(image_id)

        if not self._is_image_available(context, image):
            raise exception.ImageNotFound(image_id=image_id)

        base_image_meta = self._translate_from_glance(context, image)
        return base_image_meta

    def get_location(self, context, image_id):
        """Get backend storage location url.

        Returns a tuple containing the direct url and locations representing
        the backend storage location, or (None, None) if these attributes are
        not shown by Glance.
        """
        try:
            # direct_url is returned by v2 api
            client = GlanceClientWrapper()
            image_meta = client.call(context, 'get', image_id)
        except Exception:
            _reraise_translated_image_exception(image_id)

        if not self._is_image_available(context, image_meta):
            raise exception.ImageNotFound(image_id=image_id)

        # some glance stores like nfs only meta data
        # is stored and returned as locations.
        # so composite of two needs to be returned.
        return (getattr(image_meta, 'direct_url', None),
                getattr(image_meta, 'locations', None))

    def add_location(self, context, image_id, url, metadata):
        """Add a backend location url to an image.

        Returns a dict containing image metadata on success.
        """
        client = GlanceClientWrapper()
        try:
            return client.call(context, 'add_location',
                               image_id, url, metadata)
        except Exception:
            _reraise_translated_image_exception(image_id)

    @typing.no_type_check
    def download(self, context, image_id, data=None):
        """Calls out to Glance for data and writes data."""
        if data and 'file' in CONF.allowed_direct_url_schemes:
            direct_url, locations = self.get_location(context, image_id)
            urls = [direct_url] + [loc.get('url') for loc in locations or []]
            for url in urls:
                if url is None:
                    continue
                parsed_url = urllib.parse.urlparse(url)
                if parsed_url.scheme == "file":
                    # a system call to cp could have significant performance
                    # advantages, however we do not have the path to files at
                    # this point in the abstraction.
                    with open(parsed_url.path, "rb") as f:
                        shutil.copyfileobj(f, data)
                    return

        try:
            image_chunks = self._client.call(context, 'data', image_id)
        except Exception:
            _reraise_translated_image_exception(image_id)

        if image_chunks is None:
            raise exception.ImageDownloadFailed(
                image_href=image_id, reason=_('image contains no data.'))

        if not data:
            return image_chunks
        else:
            for chunk in image_chunks:
                data.write(chunk)

    def create(self, context, image_meta, data=None):
        """Store the image data and return the new image object."""
        sent_service_image_meta = self._translate_to_glance(image_meta)

        if data:
            sent_service_image_meta['data'] = data

        recv_service_image_meta = self._client.call(context, 'create',
                                                    **sent_service_image_meta)

        return self._translate_from_glance(context, recv_service_image_meta)

    def update(self, context, image_id,
               image_meta, data=None, purge_props=True,
               store_id=None, base_image_ref=None):
        """Modify the given image with the new data."""
        # For v2, _translate_to_glance stores custom properties in image meta
        # directly. We need the custom properties to identify properties to
        # remove if purge_props is True. Save the custom properties before
        # translate.
        if purge_props:
            props_to_update = image_meta.get('properties', {}).keys()

        image_meta = self._translate_to_glance(image_meta)

        # NOTE(bcwaldon): id is not an editable field, but it is likely to be
        # passed in by calling code. Let's be nice and ignore it.
        image_meta.pop('id', None)
        kwargs = {}
        if store_id:
            kwargs['store_id'] = store_id
        if base_image_ref:
            kwargs['base_image_ref'] = base_image_ref

        try:
            if data:
                self._client.call(context, 'upload', image_id, data, **kwargs)
            if image_meta:
                if purge_props:
                    # Properties to remove are those not specified in
                    # input properties.
                    cur_image_meta = self.show(context, image_id)
                    cur_props = cur_image_meta['properties'].keys()
                    remove_props = list(set(cur_props) -
                                        set(props_to_update))
                    image_meta['remove_props'] = remove_props
                image_meta = self._client.call(context, 'update', image_id,
                                               **image_meta)
            else:
                image_meta = self._client.call(context, 'get', image_id)
        except Exception:
            _reraise_translated_image_exception(image_id)
        else:
            return self._translate_from_glance(context, image_meta)

    def delete(self, context, image_id):
        """Delete the given image.

        :raises ImageNotFound: if the image does not exist.
        :raises NotAuthorized: if the user is not an owner.

        """
        try:
            self._client.call(context, 'delete', image_id)
        except glanceclient.exc.NotFound:
            raise exception.ImageNotFound(image_id=image_id)
        return True

    def _translate_from_glance(self, context, image) -> dict:
        """Get image metadata from glance image.

        Extract metadata from image and convert it's properties
        to type cinder expected.

        :param image: glance image object
        :return: image metadata dictionary
        """
        if self._image_schema is None:
            self._image_schema = self._client.call(context, 'get',
                                                   controller='schemas',
                                                   schema_name='image')
        # NOTE(aarefiev): get base image property, store image 'schema'
        #                 is redundant, so ignore it.
        image_meta = {key: getattr(image, key)
                      for key in image.keys()
                      if self._image_schema.is_base_property(key) is True and
                      key != 'schema'}

        # Process 'cinder_encryption_key_id' as a metadata key
        if 'cinder_encryption_key_id' in image.keys():
            image_meta['cinder_encryption_key_id'] = \
                image['cinder_encryption_key_id']

        # NOTE(aarefiev): nova is expected that all image properties
        # (custom or defined in schema-image.json) stores in
        # 'properties' key.
        image_meta['properties'] = {
            key: getattr(image, key) for key in image.keys()
            if self._image_schema.is_base_property(key) is False}

        image_meta = _convert_timestamps_to_datetimes(image_meta)
        image_meta = _convert_from_string(image_meta)
        return image_meta

    @staticmethod
    def _translate_to_glance(image_meta):
        image_meta = _convert_to_string(image_meta)
        image_meta = _remove_read_only(image_meta)

        # NOTE(tsekiyama): From the Image API v2, custom properties must
        # be stored in image_meta directly, instead of the 'properties' key.
        properties = image_meta.get('properties')
        if properties:
            image_meta.update(properties)
            del image_meta['properties']

        return image_meta

    def _is_image_available(self, context, image):
        """Check image availability.

        This check is needed in case Nova and Glance are deployed
        without authentication turned on.
        """
        # The presence of an auth token implies this is an authenticated
        # request and we need not handle the noauth use-case.
        if hasattr(context, 'auth_token') and context.auth_token:
            return True

        if image.is_public or context.is_admin:
            return True

        properties = image.properties

        if context.project_id and ('owner_id' in properties):
            return str(properties['owner_id']) == str(context.project_id)

        if context.project_id and ('project_id' in properties):
            return str(properties['project_id']) == str(context.project_id)

        if image.visibility == 'shared':
            for member in self.list_members(context, image.id):
                if (context.project_id == member['member_id'] and
                        member['status'] == 'accepted'):
                    return True

        try:
            user_id = properties['user_id']
        except KeyError:
            return False

        return str(user_id) == str(context.user_id)


def _convert_timestamps_to_datetimes(image_meta):
    """Returns image with timestamp fields converted to datetime objects."""
    for attr in ['created_at', 'updated_at', 'deleted_at']:
        if image_meta.get(attr):
            image_meta[attr] = timeutils.parse_isotime(image_meta[attr])
    return image_meta


# NOTE(bcwaldon): used to store non-string data in glance metadata
def _json_loads(properties, attr):
    prop = properties[attr]
    if isinstance(prop, str):
        properties[attr] = jsonutils.loads(prop)


def _json_dumps(properties, attr):
    prop = properties[attr]
    if not isinstance(prop, str):
        properties[attr] = jsonutils.dumps(prop)


_CONVERT_PROPS = ('block_device_mapping', 'mappings')


def _convert(method, metadata):
    metadata = copy.deepcopy(metadata)
    properties = metadata.get('properties')
    if properties:
        for attr in _CONVERT_PROPS:
            if attr in properties:
                method(properties, attr)

    return metadata


def _convert_from_string(metadata):
    return _convert(_json_loads, metadata)


def _convert_to_string(metadata):
    return _convert(_json_dumps, metadata)


def _extract_attributes(image):
    # NOTE(hdd): If a key is not found, base.Resource.__getattr__() may perform
    # a get(), resulting in a useless request back to glance. This list is
    # therefore sorted, with dependent attributes as the end
    # 'deleted_at' depends on 'deleted'
    # 'checksum' depends on 'status' == 'active'
    IMAGE_ATTRIBUTES = ['size', 'disk_format', 'owner',
                        'container_format', 'status', 'id',
                        'name', 'created_at', 'updated_at',
                        'deleted', 'deleted_at', 'checksum',
                        'min_disk', 'min_ram', 'protected',
                        'visibility',
                        'cinder_encryption_key_id']

    output: Dict[str, Any] = {}

    for attr in IMAGE_ATTRIBUTES:
        if attr == 'deleted_at' and not output['deleted']:
            output[attr] = None
        elif attr == 'checksum' and output['status'] != 'active':
            output[attr] = None
        else:
            output[attr] = getattr(image, attr, None)

    output['properties'] = getattr(image, 'properties', {})

    return output


def _remove_read_only(image_meta):
    IMAGE_ATTRIBUTES = ['status', 'updated_at', 'created_at', 'deleted_at']
    output = copy.deepcopy(image_meta)
    for attr in IMAGE_ATTRIBUTES:
        if attr in output:
            del output[attr]
    return output


def _reraise_translated_image_exception(image_id):
    """Transform the exception for the image but keep its traceback intact."""
    _exc_type, exc_value, exc_trace = sys.exc_info()
    new_exc = _translate_image_exception(image_id, exc_value)
    raise new_exc.with_traceback(exc_trace)


def _reraise_translated_exception():
    """Transform the exception but keep its traceback intact."""
    _exc_type, exc_value, exc_trace = sys.exc_info()
    new_exc = _translate_plain_exception(exc_value)
    raise new_exc.with_traceback(exc_trace)


def _translate_image_exception(image_id, exc_value):
    if isinstance(exc_value, (glanceclient.exc.Forbidden,
                              glanceclient.exc.Unauthorized)):
        return exception.ImageNotAuthorized(image_id=image_id)
    if isinstance(exc_value, glanceclient.exc.NotFound):
        return exception.ImageNotFound(image_id=image_id)
    if isinstance(exc_value, glanceclient.exc.BadRequest):
        return exception.Invalid(exc_value)
    return exc_value


def _translate_plain_exception(exc_value):
    if isinstance(exc_value, (glanceclient.exc.Forbidden,
                              glanceclient.exc.Unauthorized)):
        return exception.NotAuthorized(exc_value)
    if isinstance(exc_value, glanceclient.exc.NotFound):
        return exception.NotFound(exc_value)
    if isinstance(exc_value, glanceclient.exc.BadRequest):
        return exception.Invalid(exc_value)
    return exc_value


def get_remote_image_service(context: context.RequestContext,
                             image_href) -> Tuple[GlanceImageService, str]:
    """Create an image_service and parse the id from the given image_href.

    The image_href param can be an href of the form
    'http://example.com:9292/v1/images/b8b2c6f7-7345-4e2f-afa2-eedaba9cbbe3',
    or just an id such as 'b8b2c6f7-7345-4e2f-afa2-eedaba9cbbe3'. If the
    image_href is a standalone id, then the default image service is returned.

    :param image_href: href that describes the location of an image
    :returns: a tuple of the form (image_service, image_id)

    """
    # NOTE(bcwaldon): If image_href doesn't look like a URI, assume its a
    # standalone image ID
    if '/' not in str(image_href):
        image_service = get_default_image_service()
        return image_service, image_href

    try:
        (image_id, glance_netloc, use_ssl) = _parse_image_ref(image_href)
        glance_client = GlanceClientWrapper(context=context,
                                            netloc=glance_netloc,
                                            use_ssl=use_ssl)
    except ValueError:
        raise exception.InvalidImageRef(image_href=image_href)

    image_service = GlanceImageService(client=glance_client)
    return image_service, image_id


def get_default_image_service():
    return GlanceImageService()
