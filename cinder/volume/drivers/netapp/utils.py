# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 NetApp, Inc.
# Copyright (c) 2012 OpenStack LLC.
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

import copy
import socket

from cinder.openstack.common import log as logging
from cinder.openstack.common import timeutils
from cinder.volume.drivers.netapp.api import NaApiError
from cinder.volume.drivers.netapp.api import NaElement

LOG = logging.getLogger(__name__)


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
        raise NaApiError(code='Not found', message='No records found')

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
                node = _get_cluster_node(na_server)
                na_server.set_vserver(node)
            else:
                na_server.set_vfiler(None)
            na_server.invoke_successfully(ems, True)
            requester.last_ems = timeutils.utcnow()
            LOG.debug(_("ems executed successfully."))
        except NaApiError as e:
            LOG.debug(_("Failed to invoke ems. Message : %s") % e)


def validate_instantiation(**kwargs):
    """Checks if a driver is instantiated other than by the unified driver.

    Helps check direct instantiation of netapp drivers.
    Call this function in every netapp block driver constructor.
    """
    if kwargs and kwargs.get('netapp_mode') == 'proxy':
        return
    LOG.warn(_("It is not the recommended way to use drivers by NetApp. "
               "Please use NetAppDriver to achieve the functionality."))
