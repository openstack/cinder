# Copyright (c) 2012 NetApp, Inc.
# Copyright (c) 2012 OpenStack Foundation
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
"""
Utilities for NetApp drivers.

This module contains common utilities to be used by one or more
NetApp drivers to achieve the desired functionality.
"""

import base64
import binascii
import copy
import decimal
import socket
import uuid

import six

from cinder import context
from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import log as logging
from cinder.openstack.common import timeutils
from cinder import utils
from cinder.volume.drivers.netapp.api import NaApiError
from cinder.volume.drivers.netapp.api import NaElement
from cinder.volume.drivers.netapp.api import NaErrors
from cinder.volume.drivers.netapp.api import NaServer
from cinder.volume import volume_types


LOG = logging.getLogger(__name__)


OBSOLETE_SSC_SPECS = {'netapp:raid_type': 'netapp_raid_type',
                      'netapp:disk_type': 'netapp_disk_type'}
DEPRECATED_SSC_SPECS = {'netapp_unmirrored': 'netapp_mirrored',
                        'netapp_nodedup': 'netapp_dedup',
                        'netapp_nocompression': 'netapp_compression',
                        'netapp_thick_provisioned': 'netapp_thin_provisioned'}


def provide_ems(requester, server, stats, netapp_backend,
                server_type="cluster"):
    """Provide ems with volume stats for the requester.

    :param server_type: cluster or 7mode.
    """
    def _create_ems(stats, netapp_backend, server_type):
        """Create ems api request."""
        ems_log = NaElement('ems-autosupport-log')
        host = socket.getfqdn() or 'Cinder_node'
        dest = "cluster node" if server_type == "cluster"\
               else "7 mode controller"
        ems_log.add_new_child('computer-name', host)
        ems_log.add_new_child('event-id', '0')
        ems_log.add_new_child('event-source',
                              'Cinder driver %s' % netapp_backend)
        ems_log.add_new_child('app-version', stats.get('driver_version',
                              'Undefined'))
        ems_log.add_new_child('category', 'provisioning')
        ems_log.add_new_child('event-description',
                              'OpenStack volume created on %s' % dest)
        ems_log.add_new_child('log-level', '6')
        ems_log.add_new_child('auto-support', 'true')
        return ems_log

    def _create_vs_get():
        """Create vs_get api request."""
        vs_get = NaElement('vserver-get-iter')
        vs_get.add_new_child('max-records', '1')
        query = NaElement('query')
        query.add_node_with_children('vserver-info',
                                     **{'vserver-type': 'node'})
        vs_get.add_child_elem(query)
        desired = NaElement('desired-attributes')
        desired.add_node_with_children(
            'vserver-info', **{'vserver-name': '', 'vserver-type': ''})
        vs_get.add_child_elem(desired)
        return vs_get

    def _get_cluster_node(na_server):
        """Get the cluster node for ems."""
        na_server.set_vserver(None)
        vs_get = _create_vs_get()
        res = na_server.invoke_successfully(vs_get)
        if (res.get_child_content('num-records') and
           int(res.get_child_content('num-records')) > 0):
            attr_list = res.get_child_by_name('attributes-list')
            vs_info = attr_list.get_child_by_name('vserver-info')
            vs_name = vs_info.get_child_content('vserver-name')
            return vs_name
        return None

    do_ems = True
    if hasattr(requester, 'last_ems'):
        sec_limit = 604800
        if not (timeutils.is_older_than(requester.last_ems, sec_limit) or
                timeutils.is_older_than(requester.last_ems, sec_limit - 59)):
            do_ems = False
    if do_ems:
        na_server = copy.copy(server)
        na_server.set_timeout(25)
        ems = _create_ems(stats, netapp_backend, server_type)
        try:
            if server_type == "cluster":
                api_version = na_server.get_api_version()
                if api_version:
                    major, minor = api_version
                else:
                    raise NaApiError(code='Not found',
                                     message='No api version found')
                if major == 1 and minor > 15:
                    node = getattr(requester, 'vserver', None)
                else:
                    node = _get_cluster_node(na_server)
                if node is None:
                    raise NaApiError(code='Not found',
                                     message='No vserver found')
                na_server.set_vserver(node)
            else:
                na_server.set_vfiler(None)
            na_server.invoke_successfully(ems, True)
            LOG.debug("ems executed successfully.")
        except NaApiError as e:
            LOG.warn(_("Failed to invoke ems. Message : %s") % e)
        finally:
            requester.last_ems = timeutils.utcnow()


def validate_instantiation(**kwargs):
    """Checks if a driver is instantiated other than by the unified driver.

    Helps check direct instantiation of netapp drivers.
    Call this function in every netapp block driver constructor.
    """
    if kwargs and kwargs.get('netapp_mode') == 'proxy':
        return
    LOG.warn(_("It is not the recommended way to use drivers by NetApp. "
               "Please use NetAppDriver to achieve the functionality."))


def invoke_api(na_server, api_name, api_family='cm', query=None,
               des_result=None, additional_elems=None,
               is_iter=False, records=0, tag=None,
               timeout=0, tunnel=None):
    """Invokes any given api call to a NetApp server.

        :param na_server: na_server instance
        :param api_name: api name string
        :param api_family: cm or 7m
        :param query: api query as dict
        :param des_result: desired result as dict
        :param additional_elems: dict other than query and des_result
        :param is_iter: is iterator api
        :param records: limit for records, 0 for infinite
        :param timeout: timeout seconds
        :param tunnel: tunnel entity, vserver or vfiler name
    """
    record_step = 50
    if not (na_server or isinstance(na_server, NaServer)):
        msg = _("Requires an NaServer instance.")
        raise exception.InvalidInput(reason=msg)
    server = copy.copy(na_server)
    if api_family == 'cm':
        server.set_vserver(tunnel)
    else:
        server.set_vfiler(tunnel)
    if timeout > 0:
        server.set_timeout(timeout)
    iter_records = 0
    cond = True
    while cond:
        na_element = create_api_request(
            api_name, query, des_result, additional_elems,
            is_iter, record_step, tag)
        result = server.invoke_successfully(na_element, True)
        if is_iter:
            if records > 0:
                iter_records = iter_records + record_step
                if iter_records >= records:
                    cond = False
            tag_el = result.get_child_by_name('next-tag')
            tag = tag_el.get_content() if tag_el else None
            if not tag:
                cond = False
        else:
            cond = False
        yield result


def create_api_request(api_name, query=None, des_result=None,
                       additional_elems=None, is_iter=False,
                       record_step=50, tag=None):
    """Creates a NetApp api request.

        :param api_name: api name string
        :param query: api query as dict
        :param des_result: desired result as dict
        :param additional_elems: dict other than query and des_result
        :param is_iter: is iterator api
        :param record_step: records at a time for iter api
        :param tag: next tag for iter api
    """
    api_el = NaElement(api_name)
    if query:
        query_el = NaElement('query')
        query_el.translate_struct(query)
        api_el.add_child_elem(query_el)
    if des_result:
        res_el = NaElement('desired-attributes')
        res_el.translate_struct(des_result)
        api_el.add_child_elem(res_el)
    if additional_elems:
        api_el.translate_struct(additional_elems)
    if is_iter:
        api_el.add_new_child('max-records', str(record_step))
    if tag:
        api_el.add_new_child('tag', tag, True)
    return api_el


def to_bool(val):
    """Converts true, yes, y, 1 to True, False otherwise."""
    if val:
        strg = str(val).lower()
        if (strg == 'true' or strg == 'y'
            or strg == 'yes' or strg == 'enabled'
                or strg == '1'):
            return True
        else:
            return False
    else:
        return False


@utils.synchronized("safe_set_attr")
def set_safe_attr(instance, attr, val):
    """Sets the attribute in a thread safe manner.

    Returns if new val was set on attribute.
    If attr already had the value then False.
    """

    if not instance or not attr:
        return False
    old_val = getattr(instance, attr, None)
    if val is None and old_val is None:
        return False
    elif val == old_val:
        return False
    else:
        setattr(instance, attr, val)
        return True


def get_volume_extra_specs(volume):
    """Provides extra specs associated with volume."""
    ctxt = context.get_admin_context()
    type_id = volume.get('volume_type_id')
    specs = None
    if type_id is not None:
        volume_type = volume_types.get_volume_type(ctxt, type_id)
        specs = volume_type.get('extra_specs')
    return specs


def check_apis_on_cluster(na_server, api_list=None):
    """Checks api availability and permissions on cluster.

    Checks api availability and permissions for executing user.
    Returns a list of failed apis.
    """
    api_list = api_list or []
    failed_apis = []
    if api_list:
        api_version = na_server.get_api_version()
        if api_version:
            major, minor = api_version
            if major == 1 and minor < 20:
                for api_name in api_list:
                    na_el = NaElement(api_name)
                    try:
                        na_server.invoke_successfully(na_el)
                    except Exception as e:
                        if isinstance(e, NaApiError):
                            if (e.code == NaErrors['API_NOT_FOUND'].code or
                                    e.code ==
                                    NaErrors['INSUFFICIENT_PRIVS'].code):
                                failed_apis.append(api_name)
            elif major == 1 and minor >= 20:
                failed_apis = copy.copy(api_list)
                result = invoke_api(
                    na_server,
                    api_name='system-user-capability-get-iter',
                    api_family='cm',
                    additional_elems=None,
                    is_iter=True)
                for res in result:
                    attr_list = res.get_child_by_name('attributes-list')
                    if attr_list:
                        capabilities = attr_list.get_children()
                        for capability in capabilities:
                            op_list = capability.get_child_by_name(
                                'operation-list')
                            if op_list:
                                ops = op_list.get_children()
                                for op in ops:
                                    apis = op.get_child_content('api-name')
                                    if apis:
                                        api_list = apis.split(',')
                                        for api_name in api_list:
                                            if (api_name and
                                                    api_name.strip()
                                                    in failed_apis):
                                                failed_apis.remove(api_name)
                                    else:
                                        continue
            else:
                msg = _("Unsupported Clustered Data ONTAP version.")
                raise exception.VolumeBackendAPIException(data=msg)
        else:
            msg = _("Api version could not be determined.")
            raise exception.VolumeBackendAPIException(data=msg)
    return failed_apis


def resolve_hostname(hostname):
    """Resolves host name to IP address."""
    res = socket.getaddrinfo(hostname, None)[0]
    family, socktype, proto, canonname, sockaddr = res
    return sockaddr[0]


def encode_hex_to_base32(hex_string):
    """Encodes hex to base32 bit as per RFC4648."""
    bin_form = binascii.unhexlify(hex_string)
    return base64.b32encode(bin_form)


def decode_base32_to_hex(base32_string):
    """Decodes base32 string to hex string."""
    bin_form = base64.b32decode(base32_string)
    return binascii.hexlify(bin_form)


def convert_uuid_to_es_fmt(uuid_str):
    """Converts uuid to e-series compatible name format."""
    uuid_base32 = encode_hex_to_base32(uuid.UUID(str(uuid_str)).hex)
    return uuid_base32.strip('=')


def convert_es_fmt_to_uuid(es_label):
    """Converts e-series name format to uuid."""
    es_label_b32 = es_label.ljust(32, '=')
    return uuid.UUID(binascii.hexlify(base64.b32decode(es_label_b32)))


def round_down(value, precision):
    return float(decimal.Decimal(six.text_type(value)).quantize(
        decimal.Decimal(precision), rounding=decimal.ROUND_DOWN))


def log_extra_spec_warnings(extra_specs):
    for spec in (set(extra_specs.keys() if extra_specs else []) &
                 set(OBSOLETE_SSC_SPECS.keys())):
            msg = _('Extra spec %(old)s is obsolete.  Use %(new)s instead.')
            args = {'old': spec, 'new': OBSOLETE_SSC_SPECS[spec]}
            LOG.warn(msg % args)
    for spec in (set(extra_specs.keys() if extra_specs else []) &
                 set(DEPRECATED_SSC_SPECS.keys())):
            msg = _('Extra spec %(old)s is deprecated.  Use %(new)s instead.')
            args = {'old': spec, 'new': DEPRECATED_SSC_SPECS[spec]}
            LOG.warn(msg % args)
