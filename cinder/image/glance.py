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


from __future__ import absolute_import

import copy
import itertools
import random
import shutil
import sys
import time

import glanceclient.exc
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import timeutils
import six
from six.moves import range
from six.moves import urllib

from cinder import exception
from cinder.i18n import _LE, _LW


glance_opts = [
    cfg.ListOpt('allowed_direct_url_schemes',
                default=[],
                help='A list of url schemes that can be downloaded directly '
                     'via the direct_url.  Currently supported schemes: '
                     '[file].'),
]
glance_core_properties_opts = [
    cfg.ListOpt('glance_core_properties',
                default=['checksum', 'container_format',
                         'disk_format', 'image_name', 'image_id',
                         'min_disk', 'min_ram', 'name', 'size'],
                help='Default core properties of image')
]
CONF = cfg.CONF
CONF.register_opts(glance_opts)
CONF.register_opts(glance_core_properties_opts)
CONF.import_opt('glance_api_version', 'cinder.common.config')

LOG = logging.getLogger(__name__)


def _parse_image_ref(image_href):
    """Parse an image href into composite parts.

    :param image_href: href of an image
    :returns: a tuple of the form (image_id, netloc, use_ssl)
    :raises ValueError

    """
    url = urllib.parse.urlparse(image_href)
    netloc = url.netloc
    image_id = url.path.split('/')[-1]
    use_ssl = (url.scheme == 'https')
    return (image_id, netloc, use_ssl)


def _create_glance_client(context, netloc, use_ssl, version=None):
    """Instantiate a new glanceclient.Client object."""
    if version is None:
        version = CONF.glance_api_version
    params = {}
    if use_ssl:
        scheme = 'https'
        # https specific params
        params['insecure'] = CONF.glance_api_insecure
        params['ssl_compression'] = CONF.glance_api_ssl_compression
        params['cacert'] = CONF.glance_ca_certificates_file
    else:
        scheme = 'http'
    if CONF.auth_strategy == 'keystone':
        params['token'] = context.auth_token
    if CONF.glance_request_timeout is not None:
        params['timeout'] = CONF.glance_request_timeout
    endpoint = '%s://%s' % (scheme, netloc)
    return glanceclient.Client(str(version), endpoint, **params)


def get_api_servers():
    """Return Iterable over shuffled api servers.

    Shuffle a list of CONF.glance_api_servers and return an iterator
    that will cycle through the list, looping around to the beginning
    if necessary.
    """
    api_servers = []
    for api_server in CONF.glance_api_servers:
        if '//' not in api_server:
            api_server = 'http://' + api_server
        url = urllib.parse.urlparse(api_server)
        netloc = url.netloc
        use_ssl = (url.scheme == 'https')
        api_servers.append((netloc, use_ssl))
    random.shuffle(api_servers)
    return itertools.cycle(api_servers)


class GlanceClientWrapper(object):
    """Glance client wrapper class that implements retries."""

    def __init__(self, context=None, netloc=None, use_ssl=False,
                 version=None):
        if netloc is not None:
            self.client = self._create_static_client(context,
                                                     netloc,
                                                     use_ssl, version)
        else:
            self.client = None
        self.api_servers = None
        self.version = version

        if CONF.glance_num_retries < 0:
            LOG.warning(_LW(
                "glance_num_retries shouldn't be a negative value. "
                "The number of retries will be set to 0 until this is"
                "corrected in the cinder.conf."))
            CONF.set_override('glance_num_retries', 0)

    def _create_static_client(self, context, netloc, use_ssl, version):
        """Create a client that we'll use for every call."""
        self.netloc = netloc
        self.use_ssl = use_ssl
        self.version = version
        return _create_glance_client(context,
                                     self.netloc,
                                     self.use_ssl, self.version)

    def _create_onetime_client(self, context, version):
        """Create a client that will be used for one call."""
        if self.api_servers is None:
            self.api_servers = get_api_servers()
        self.netloc, self.use_ssl = next(self.api_servers)
        return _create_glance_client(context,
                                     self.netloc,
                                     self.use_ssl, version)

    def call(self, context, method, *args, **kwargs):
        """Call a glance client method.

        If we get a connection error,
        retry the request according to CONF.glance_num_retries.
        """
        version = kwargs.pop('version', self.version)

        retry_excs = (glanceclient.exc.ServiceUnavailable,
                      glanceclient.exc.InvalidEndpoint,
                      glanceclient.exc.CommunicationError)
        num_attempts = 1 + CONF.glance_num_retries

        for attempt in range(1, num_attempts + 1):
            client = self.client or self._create_onetime_client(context,
                                                                version)
            try:
                controller = getattr(client,
                                     kwargs.pop('controller', 'images'))
                return getattr(controller, method)(*args, **kwargs)
            except retry_excs as e:
                netloc = self.netloc
                extra = "retrying"
                error_msg = _LE("Error contacting glance server "
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

        # ensure filters is a dict
        _params.setdefault('filters', {})
        # NOTE(vish): don't filter out private images
        _params['filters'].setdefault('is_public', 'none')

        return _params

    def show(self, context, image_id):
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
        if CONF.glance_api_version == 1:
            # image location not available in v1
            return (None, None)
        try:
            # direct_url is returned by v2 api
            client = GlanceClientWrapper(version=2)
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
        if CONF.glance_api_version != 2:
            raise exception.Invalid("Image API version 2 is disabled.")
        client = GlanceClientWrapper(version=2)
        try:
            return client.call(context, 'add_location',
                               image_id, url, metadata)
        except Exception:
            _reraise_translated_image_exception(image_id)

    def delete_locations(self, context, image_id, url_set):
        """Delete backend location urls from an image."""
        if CONF.glance_api_version != 2:
            raise exception.Invalid("Image API version 2 is disabled.")
        client = GlanceClientWrapper(version=2)
        try:
            return client.call(context, 'delete_locations', image_id, url_set)
        except Exception:
            _reraise_translated_image_exception(image_id)

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
                    with open(parsed_url.path, "r") as f:
                        shutil.copyfileobj(f, data)
                    return

        try:
            image_chunks = self._client.call(context, 'data', image_id)
        except Exception:
            _reraise_translated_image_exception(image_id)

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
               image_meta, data=None, purge_props=True):
        """Modify the given image with the new data."""
        image_meta = self._translate_to_glance(image_meta)
        # NOTE(dosaboy): see comment in bug 1210467
        if CONF.glance_api_version == 1:
            image_meta['purge_props'] = purge_props
        # NOTE(bcwaldon): id is not an editable field, but it is likely to be
        # passed in by calling code. Let's be nice and ignore it.
        image_meta.pop('id', None)
        if data:
            image_meta['data'] = data
        try:
            # NOTE(dosaboy): the v2 api separates update from upload
            if data and CONF.glance_api_version > 1:
                self._client.call(context, 'upload', image_id, data)
                image_meta = self._client.call(context, 'get', image_id)
            else:
                image_meta = self._client.call(context, 'update', image_id,
                                               **image_meta)
        except Exception:
            _reraise_translated_image_exception(image_id)
        else:
            return self._translate_from_glance(context, image_meta)

    def delete(self, context, image_id):
        """Delete the given image.

        :raises: ImageNotFound if the image does not exist.
        :raises: NotAuthorized if the user is not an owner.

        """
        try:
            self._client.call(context, 'delete', image_id)
        except glanceclient.exc.NotFound:
            raise exception.ImageNotFound(image_id=image_id)
        return True

    def _translate_from_glance(self, context, image):
        """Get image metadata from glance image.

        Extract metadata from image and convert it's properties
        to type cinder expected.

        :param image: glance image object
        :return: image metadata dictionary
        """
        if CONF.glance_api_version == 2:
            if self._image_schema is None:
                self._image_schema = self._client.call(context, 'get',
                                                       controller='schemas',
                                                       schema_name='image',
                                                       version=2)
            # NOTE(aarefiev): get base image property, store image 'schema'
            #                 is redundant, so ignore it.
            image_meta = {key: getattr(image, key)
                          for key in image.keys()
                          if self._image_schema.is_base_property(key) is True
                          and key != 'schema'}

            # NOTE(aarefiev): nova is expected that all image properties
            # (custom or defined in schema-image.json) stores in
            # 'properties' key.
            image_meta['properties'] = {
                key: getattr(image, key) for key in image.keys()
                if self._image_schema.is_base_property(key) is False}
        else:
            image_meta = _extract_attributes(image)

        image_meta = _convert_timestamps_to_datetimes(image_meta)
        image_meta = _convert_from_string(image_meta)
        return image_meta

    @staticmethod
    def _translate_to_glance(image_meta):
        image_meta = _convert_to_string(image_meta)
        image_meta = _remove_read_only(image_meta)
        return image_meta

    @staticmethod
    def _is_image_available(context, image):
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
    if isinstance(prop, six.string_types):
        properties[attr] = jsonutils.loads(prop)


def _json_dumps(properties, attr):
    prop = properties[attr]
    if not isinstance(prop, six.string_types):
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
                        'min_disk', 'min_ram', 'is_public']
    output = {}

    for attr in IMAGE_ATTRIBUTES:
        if attr == 'deleted_at' and not output['deleted']:
            output[attr] = None
        elif attr == 'checksum' and output['status'] != 'active':
            output[attr] = None
        else:
            output[attr] = getattr(image, attr, None)

    output['properties'] = getattr(image, 'properties', {})

    # NOTE(jbernard): Update image properties for API version 2.  For UEC
    # images stored in glance, the necessary boot information is stored in the
    # properties dict in version 1 so there is nothing more to do.  However, in
    # version 2 these are standalone fields in the GET response.  This bit of
    # code moves them back into the properties dict as the caller expects, thus
    # producing a volume with correct metadata for booting.
    for attr in ('kernel_id', 'ramdisk_id'):
        value = getattr(image, attr, None)
        if value:
            output['properties'][attr] = value

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
    six.reraise(type(new_exc), new_exc, exc_trace)


def _reraise_translated_exception():
    """Transform the exception but keep its traceback intact."""
    _exc_type, exc_value, exc_trace = sys.exc_info()
    new_exc = _translate_plain_exception(exc_value)
    six.reraise(type(new_exc), new_exc, exc_trace)


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


def get_remote_image_service(context, image_href):
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
