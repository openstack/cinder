# Copyright (c) 2012 NetApp, Inc.  All rights reserved.
# Copyright (c) 2014 Navneet Singh.  All rights reserved.
# Copyright (c) 2014 Clinton Knight.  All rights reserved.
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


import decimal
import platform
import socket

from oslo_concurrency import processutils as putils
import six

from cinder import context
from cinder import exception
from cinder.i18n import _, _LW, _LI
from cinder.openstack.common import log as logging
<<<<<<< HEAD
from cinder.openstack.common import processutils as putils
from cinder.openstack.common import timeutils
from cinder import utils
from cinder import version
from cinder.volume.drivers.netapp.api import NaApiError
from cinder.volume.drivers.netapp.api import NaElement
from cinder.volume.drivers.netapp.api import NaErrors
from cinder.volume.drivers.netapp.api import NaServer
=======
from cinder import utils
from cinder import version
>>>>>>> 8bb5554537b34faead2b5eaf6d29600ff8243e85
from cinder.volume import volume_types


LOG = logging.getLogger(__name__)


OBSOLETE_SSC_SPECS = {'netapp:raid_type': 'netapp_raid_type',
                      'netapp:disk_type': 'netapp_disk_type'}
DEPRECATED_SSC_SPECS = {'netapp_unmirrored': 'netapp_mirrored',
                        'netapp_nodedup': 'netapp_dedup',
                        'netapp_nocompression': 'netapp_compression',
                        'netapp_thick_provisioned': 'netapp_thin_provisioned'}
<<<<<<< HEAD


def provide_ems(requester, server, netapp_backend, app_version,
                server_type="cluster"):
    """Provide ems with volume stats for the requester.

    :param server_type: cluster or 7mode.
    """

    def _create_ems(netapp_backend, app_version, server_type):
        """Create ems api request."""
        ems_log = NaElement('ems-autosupport-log')
        host = socket.getfqdn() or 'Cinder_node'
        if server_type == "cluster":
            dest = "cluster node"
        else:
            dest = "7 mode controller"
        ems_log.add_new_child('computer-name', host)
        ems_log.add_new_child('event-id', '0')
        ems_log.add_new_child('event-source',
                              'Cinder driver %s' % netapp_backend)
        ems_log.add_new_child('app-version', app_version)
        ems_log.add_new_child('category', 'provisioning')
        ems_log.add_new_child('event-description',
                              'OpenStack Cinder connected to %s' % dest)
        ems_log.add_new_child('log-level', '6')
        ems_log.add_new_child('auto-support', 'false')
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
        sec_limit = 3559
        if not (timeutils.is_older_than(requester.last_ems, sec_limit)):
            do_ems = False
    if do_ems:
        na_server = copy.copy(server)
        na_server.set_timeout(25)
        ems = _create_ems(netapp_backend, app_version, server_type)
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
=======
>>>>>>> 8bb5554537b34faead2b5eaf6d29600ff8243e85


def validate_instantiation(**kwargs):
    """Checks if a driver is instantiated other than by the unified driver.

    Helps check direct instantiation of netapp drivers.
    Call this function in every netapp block driver constructor.
    """
    if kwargs and kwargs.get('netapp_mode') == 'proxy':
        return
    LOG.warning(_LW("It is not the recommended way to use drivers by NetApp. "
                    "Please use NetAppDriver to achieve the functionality."))


def check_flags(required_flags, configuration):
    """Ensure that the flags we care about are set."""
    for flag in required_flags:
        if not getattr(configuration, flag, None):
            msg = _('Configuration value %s is not set.') % flag
            raise exception.InvalidInput(reason=msg)


def to_bool(val):
    """Converts true, yes, y, 1 to True, False otherwise."""
    if val:
        strg = six.text_type(val).lower()
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


def resolve_hostname(hostname):
    """Resolves host name to IP address."""
    res = socket.getaddrinfo(hostname, None)[0]
    family, socktype, proto, canonname, sockaddr = res
    return sockaddr[0]


def round_down(value, precision):
    return float(decimal.Decimal(six.text_type(value)).quantize(
        decimal.Decimal(precision), rounding=decimal.ROUND_DOWN))


def log_extra_spec_warnings(extra_specs):
    for spec in (set(extra_specs.keys() if extra_specs else []) &
                 set(OBSOLETE_SSC_SPECS.keys())):
            msg = _LW('Extra spec %(old)s is obsolete.  Use %(new)s instead.')
            args = {'old': spec, 'new': OBSOLETE_SSC_SPECS[spec]}
            LOG.warning(msg % args)
    for spec in (set(extra_specs.keys() if extra_specs else []) &
                 set(DEPRECATED_SSC_SPECS.keys())):
            msg = _LW('Extra spec %(old)s is deprecated.  Use %(new)s '
                      'instead.')
            args = {'old': spec, 'new': DEPRECATED_SSC_SPECS[spec]}
            LOG.warning(msg % args)


def get_iscsi_connection_properties(lun_id, volume, iqn,
                                    address, port):

        properties = {}
        properties['target_discovered'] = False
        properties['target_portal'] = '%s:%s' % (address, port)
        properties['target_iqn'] = iqn
        properties['target_lun'] = int(lun_id)
        properties['volume_id'] = volume['id']
        auth = volume['provider_auth']
        if auth:
            (auth_method, auth_username, auth_secret) = auth.split()
            properties['auth_method'] = auth_method
            properties['auth_username'] = auth_username
            properties['auth_password'] = auth_secret
        return {
            'driver_volume_type': 'iscsi',
            'data': properties,
        }


class hashabledict(dict):
    """A hashable dictionary that is comparable (i.e. in unit tests, etc.)"""
    def __hash__(self):
        return hash(tuple(sorted(self.items())))


class OpenStackInfo(object):
    """OS/distribution, release, and version.

    NetApp uses these fields as content for EMS log entry.
    """

    PACKAGE_NAME = 'python-cinder'

    def __init__(self):
        self._version = 'unknown version'
        self._release = 'unknown release'
        self._vendor = 'unknown vendor'
        self._platform = 'unknown platform'

    def _update_version_from_version_string(self):
        try:
            self._version = version.version_info.version_string()
        except Exception:
            pass

    def _update_release_from_release_string(self):
        try:
            self._release = version.version_info.release_string()
        except Exception:
            pass

    def _update_platform(self):
        try:
            self._platform = platform.platform()
        except Exception:
            pass

<<<<<<< HEAD
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


def get_iscsi_connection_properties(address, port, iqn, lun_id, volume):
        properties = {}
        properties['target_discovered'] = False
        properties['target_portal'] = '%s:%s' % (address, port)
        properties['target_iqn'] = iqn
        properties['target_lun'] = int(lun_id)
        properties['volume_id'] = volume['id']
        auth = volume['provider_auth']
        if auth:
            (auth_method, auth_username, auth_secret) = auth.split()
            properties['auth_method'] = auth_method
            properties['auth_username'] = auth_username
            properties['auth_password'] = auth_secret
        return {
            'driver_volume_type': 'iscsi',
            'data': properties,
        }


class OpenStackInfo(object):
    """OS/distribution, release, and version.

    NetApp uses these fields as content for EMS log entry.
    """

    PACKAGE_NAME = 'python-cinder'

    def __init__(self):
        self._version = 'unknown version'
        self._release = 'unknown release'
        self._vendor = 'unknown vendor'
        self._platform = 'unknown platform'

    def _update_version_from_version_string(self):
        try:
            self._version = version.version_info.version_string()
        except Exception:
            pass

    def _update_release_from_release_string(self):
        try:
            self._release = version.version_info.release_string()
        except Exception:
            pass

    def _update_platform(self):
        try:
            self._platform = platform.platform()
        except Exception:
            pass

=======
>>>>>>> 8bb5554537b34faead2b5eaf6d29600ff8243e85
    @staticmethod
    def _get_version_info_version():
        return version.version_info.version

    @staticmethod
    def _get_version_info_release():
        return version.version_info.release

    def _update_info_from_version_info(self):
        try:
            ver = self._get_version_info_version()
            if ver:
                self._version = ver
        except Exception:
            pass
        try:
            rel = self._get_version_info_release()
            if rel:
                self._release = rel
        except Exception:
            pass

    # RDO, RHEL-OSP, Mirantis on Redhat, SUSE
    def _update_info_from_rpm(self):
        LOG.debug('Trying rpm command.')
        try:
            out, err = putils.execute("rpm", "-q", "--queryformat",
                                      "'%{version}\t%{release}\t%{vendor}'",
                                      self.PACKAGE_NAME)
            if not out:
<<<<<<< HEAD
                LOG.info(_('No rpm info found for %(pkg)s package.') % {
=======
                LOG.info(_LI('No rpm info found for %(pkg)s package.') % {
>>>>>>> 8bb5554537b34faead2b5eaf6d29600ff8243e85
                    'pkg': self.PACKAGE_NAME})
                return False
            parts = out.split()
            self._version = parts[0]
            self._release = parts[1]
            self._vendor = ' '.join(parts[2::])
            return True
        except Exception as e:
<<<<<<< HEAD
            LOG.info(_('Could not run rpm command: %(msg)s.') % {
                'msg': e})
=======
            LOG.info(_LI('Could not run rpm command: %(msg)s.') % {'msg': e})
>>>>>>> 8bb5554537b34faead2b5eaf6d29600ff8243e85
            return False

    # ubuntu, mirantis on ubuntu
    def _update_info_from_dpkg(self):
        LOG.debug('Trying dpkg-query command.')
        try:
            _vendor = None
            out, err = putils.execute("dpkg-query", "-W", "-f='${Version}'",
                                      self.PACKAGE_NAME)
            if not out:
<<<<<<< HEAD
                LOG.info(_('No dpkg-query info found for %(pkg)s package.') % {
                    'pkg': self.PACKAGE_NAME})
=======
                LOG.info(_LI('No dpkg-query info found for %(pkg)s package.')
                         % {'pkg': self.PACKAGE_NAME})
>>>>>>> 8bb5554537b34faead2b5eaf6d29600ff8243e85
                return False
            # debian format: [epoch:]upstream_version[-debian_revision]
            deb_version = out
            # in case epoch or revision is missing, copy entire string
            _release = deb_version
            if ':' in deb_version:
                deb_epoch, upstream_version = deb_version.split(':')
                _release = upstream_version
            if '-' in deb_version:
                deb_revision = deb_version.split('-')[1]
                _vendor = deb_revision
            self._release = _release
            if _vendor:
                self._vendor = _vendor
            return True
        except Exception as e:
<<<<<<< HEAD
            LOG.info(_('Could not run dpkg-query command: %(msg)s.') % {
=======
            LOG.info(_LI('Could not run dpkg-query command: %(msg)s.') % {
>>>>>>> 8bb5554537b34faead2b5eaf6d29600ff8243e85
                'msg': e})
            return False

    def _update_openstack_info(self):
        self._update_version_from_version_string()
        self._update_release_from_release_string()
        self._update_platform()
        # some distributions override with more meaningful information
        self._update_info_from_version_info()
        # see if we have still more targeted info from rpm or apt
        found_package = self._update_info_from_rpm()
        if not found_package:
            self._update_info_from_dpkg()

    def info(self):
        self._update_openstack_info()
        return '%(version)s|%(release)s|%(vendor)s|%(platform)s' % {
            'version': self._version, 'release': self._release,
            'vendor': self._vendor, 'platform': self._platform}
