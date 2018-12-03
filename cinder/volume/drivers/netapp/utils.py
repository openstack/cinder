# Copyright (c) 2012 NetApp, Inc.  All rights reserved.
# Copyright (c) 2014 Navneet Singh.  All rights reserved.
# Copyright (c) 2014 Clinton Knight.  All rights reserved.
# Copyright (c) 2015 Tom Barron.  All rights reserved.
# Copyright (c) 2016 Michael Price.  All rights reserved.
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
import re

from oslo_concurrency import processutils as putils
from oslo_log import log as logging
from oslo_utils import netutils
import six

from cinder import context
from cinder import exception
from cinder.i18n import _
from cinder import utils
from cinder import version
from cinder.volume import qos_specs
from cinder.volume import volume_types


LOG = logging.getLogger(__name__)


OPENSTACK_PREFIX = 'openstack-'
OBSOLETE_SSC_SPECS = {'netapp:raid_type': 'netapp_raid_type',
                      'netapp:disk_type': 'netapp_disk_type'}
DEPRECATED_SSC_SPECS = {'netapp_unmirrored': 'netapp_mirrored',
                        'netapp_nodedup': 'netapp_dedup',
                        'netapp_nocompression': 'netapp_compression',
                        'netapp_thick_provisioned': 'netapp_thin_provisioned'}
QOS_KEYS = frozenset(['maxIOPS', 'maxIOPSperGiB', 'maxBPS', 'maxBPSperGiB'])
BACKEND_QOS_CONSUMERS = frozenset(['back-end', 'both'])

# Secret length cannot be less than 96 bits. http://tools.ietf.org/html/rfc3723
CHAP_SECRET_LENGTH = 16
DEFAULT_CHAP_USER_NAME = 'NetApp_iSCSI_CHAP_Username'
API_TRACE_PATTERN = '(.*)'


def validate_instantiation(**kwargs):
    """Checks if a driver is instantiated other than by the unified driver.

    Helps check direct instantiation of netapp drivers.
    Call this function in every netapp block driver constructor.
    """
    if kwargs and kwargs.get('netapp_mode') == 'proxy':
        return
    LOG.warning("It is not the recommended way to use drivers by NetApp. "
                "Please use NetAppDriver to achieve the functionality.")


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
    if type_id is None:
        return {}
    volume_type = volume_types.get_volume_type(ctxt, type_id)
    if volume_type is None:
        return {}
    extra_specs = volume_type.get('extra_specs', {})
    log_extra_spec_warnings(extra_specs)
    return extra_specs


def setup_api_trace_pattern(api_trace_pattern):
    global API_TRACE_PATTERN
    try:
        re.compile(api_trace_pattern)
    except (re.error, TypeError):
        msg = _('Cannot parse the API trace pattern. %s is not a '
                'valid python regular expression.') % api_trace_pattern
        raise exception.InvalidConfigurationValue(reason=msg)
    API_TRACE_PATTERN = api_trace_pattern


def trace_filter_func_api(all_args):
    na_element = all_args.get('na_element')
    if na_element is None:
        return True
    api_name = na_element.get_name()
    return re.match(API_TRACE_PATTERN, api_name) is not None


def round_down(value, precision='0.00'):
    return float(decimal.Decimal(six.text_type(value)).quantize(
        decimal.Decimal(precision), rounding=decimal.ROUND_DOWN))


def log_extra_spec_warnings(extra_specs):
    for spec in (set(extra_specs.keys() if extra_specs else []) &
                 set(OBSOLETE_SSC_SPECS.keys())):
        LOG.warning('Extra spec %(old)s is obsolete.  Use %(new)s '
                    'instead.', {'old': spec,
                                 'new': OBSOLETE_SSC_SPECS[spec]})
    for spec in (set(extra_specs.keys() if extra_specs else []) &
                 set(DEPRECATED_SSC_SPECS.keys())):
        LOG.warning('Extra spec %(old)s is deprecated.  Use %(new)s '
                    'instead.', {'old': spec,
                                 'new': DEPRECATED_SSC_SPECS[spec]})


def get_iscsi_connection_properties(lun_id, volume, iqns,
                                    addresses, ports):
    # literal ipv6 address
    addresses = [netutils.escape_ipv6(a) if netutils.is_valid_ipv6(a) else a
                 for a in addresses]

    lun_id = int(lun_id)
    if isinstance(iqns, six.string_types):
        iqns = [iqns] * len(addresses)

    target_portals = ['%s:%s' % (a, p) for a, p in zip(addresses, ports)]

    properties = {}
    properties['target_discovered'] = False
    properties['target_portal'] = target_portals[0]
    properties['target_iqn'] = iqns[0]
    properties['target_lun'] = lun_id
    properties['volume_id'] = volume['id']
    if len(addresses) > 1:
        properties['target_portals'] = target_portals
        properties['target_iqns'] = iqns
        properties['target_luns'] = [lun_id] * len(addresses)

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


def validate_qos_spec(qos_spec):
    """Check validity of Cinder qos spec for our backend."""
    if qos_spec is None:
        return
    normalized_qos_keys = [key.lower() for key in QOS_KEYS]
    keylist = []
    for key, value in qos_spec.items():
        lower_case_key = key.lower()
        if lower_case_key not in normalized_qos_keys:
            msg = _('Unrecognized QOS keyword: "%s"') % key
            raise exception.Invalid(msg)
        keylist.append(lower_case_key)
    # Modify the following check when we allow multiple settings in one spec.
    if len(keylist) > 1:
        msg = _('Only one limit can be set in a QoS spec.')
        raise exception.Invalid(msg)


def get_volume_type_from_volume(volume):
    """Provides volume type associated with volume."""
    type_id = volume.get('volume_type_id')
    if type_id is None:
        return {}
    ctxt = context.get_admin_context()
    return volume_types.get_volume_type(ctxt, type_id)


def map_qos_spec(qos_spec, volume):
    """Map Cinder QOS spec to limit/throughput-value as used in client API."""
    if qos_spec is None:
        return None

    qos_spec = map_dict_to_lower(qos_spec)
    spec = dict(policy_name=get_qos_policy_group_name(volume),
                max_throughput=None)

    # QoS specs are exclusive of one another.
    if 'maxiops' in qos_spec:
        spec['max_throughput'] = '%siops' % qos_spec['maxiops']
    elif 'maxiopspergib' in qos_spec:
        spec['max_throughput'] = '%siops' % six.text_type(
            int(qos_spec['maxiopspergib']) * int(volume['size']))
    elif 'maxbps' in qos_spec:
        spec['max_throughput'] = '%sB/s' % qos_spec['maxbps']
    elif 'maxbpspergib' in qos_spec:
        spec['max_throughput'] = '%sB/s' % six.text_type(
            int(qos_spec['maxbpspergib']) * int(volume['size']))

    return spec


def map_dict_to_lower(input_dict):
    """Return an equivalent to the input dictionary with lower-case keys."""
    lower_case_dict = {}
    for key in input_dict:
        lower_case_dict[key.lower()] = input_dict[key]
    return lower_case_dict


def get_qos_policy_group_name(volume):
    """Return the name of backend QOS policy group based on its volume id."""
    if 'id' in volume:
        return OPENSTACK_PREFIX + volume['id']
    return None


def get_qos_policy_group_name_from_info(qos_policy_group_info):
    """Return the name of a QOS policy group given qos policy group info."""
    if qos_policy_group_info is None:
        return None
    legacy = qos_policy_group_info.get('legacy')
    if legacy is not None:
        return legacy['policy_name']
    spec = qos_policy_group_info.get('spec')
    if spec is not None:
        return spec['policy_name']
    return None


def get_pool_name_filter_regex(configuration):
    """Build the regex for filtering pools by name

    :param configuration: The volume driver configuration
    :raise InvalidConfigurationValue: if configured regex pattern is invalid
    :returns: A compiled regex for filtering pool names
    """

    # If the configuration parameter is specified as an empty string
    # (interpreted as matching all pools), we replace it here with
    # (.+) to be explicit with CSV compatibility support implemented below.
    pool_patterns = configuration.netapp_pool_name_search_pattern or r'(.+)'

    # Strip whitespace from start/end and then 'or' all regex patterns
    pool_patterns = '|'.join(['^' + pool_pattern.strip('^$ \t') + '$' for
                              pool_pattern in pool_patterns.split(',')])

    try:
        return re.compile(pool_patterns)
    except re.error:
        raise exception.InvalidConfigurationValue(
            option='netapp_pool_name_search_pattern',
            value=configuration.netapp_pool_name_search_pattern)


def get_valid_qos_policy_group_info(volume, extra_specs=None):
    """Given a volume, return information for QOS provisioning."""
    info = dict(legacy=None, spec=None)
    try:
        volume_type = get_volume_type_from_volume(volume)
    except KeyError:
        LOG.exception('Cannot get QoS spec for volume %s.', volume['id'])
        return info
    if volume_type is None:
        return info
    if extra_specs is None:
        extra_specs = volume_type.get('extra_specs', {})
    info['legacy'] = get_legacy_qos_policy(extra_specs)
    info['spec'] = get_valid_backend_qos_spec_from_volume_type(volume,
                                                               volume_type)
    msg = 'QoS policy group info for volume %(vol)s: %(info)s'
    LOG.debug(msg, {'vol': volume['name'], 'info': info})
    check_for_invalid_qos_spec_combination(info, volume_type)
    return info


def get_valid_backend_qos_spec_from_volume_type(volume, volume_type):
    """Given a volume type, return the associated Cinder QoS spec."""
    spec_key_values = get_backend_qos_spec_from_volume_type(volume_type)
    if spec_key_values is None:
        return None
    validate_qos_spec(spec_key_values)
    return map_qos_spec(spec_key_values, volume)


def get_backend_qos_spec_from_volume_type(volume_type):
    qos_specs_id = volume_type.get('qos_specs_id')
    if qos_specs_id is None:
        return None
    ctxt = context.get_admin_context()
    qos_spec = qos_specs.get_qos_specs(ctxt, qos_specs_id)
    if qos_spec is None:
        return None
    consumer = qos_spec['consumer']
    # Front end QoS specs are handled by libvirt and we ignore them here.
    if consumer not in BACKEND_QOS_CONSUMERS:
        return None
    spec_key_values = qos_spec['specs']
    return spec_key_values


def check_for_invalid_qos_spec_combination(info, volume_type):
    """Invalidate QOS spec if both legacy and non-legacy info is present."""
    if info['legacy'] and info['spec']:
        msg = _('Conflicting QoS specifications in volume type '
                '%s: when QoS spec is associated to volume '
                'type, legacy "netapp:qos_policy_group" is not allowed in '
                'the volume type extra specs.') % volume_type['id']
        raise exception.Invalid(msg)


def get_legacy_qos_policy(extra_specs):
    """Return legacy qos policy information if present in extra specs."""
    external_policy_name = extra_specs.get('netapp:qos_policy_group')
    if external_policy_name is None:
        return None
    return dict(policy_name=external_policy_name)


def get_export_host_junction_path(share):
    if '[' in share and ']' in share:
        try:
            # ipv6
            host = re.search('\[(.*)\]', share).group(1)
            junction_path = share.split(':')[-1]
        except AttributeError:
            raise exception.NetAppDriverException(_("Share '%s' is "
                                                    "not in a valid "
                                                    "format.") % share)
    else:
        # ipv4
        path = share.split(':')
        if len(path) == 2:
            host = path[0]
            junction_path = path[1]
        else:
            raise exception.NetAppDriverException(_("Share '%s' is "
                                                    "not in a valid "
                                                    "format.") % share)

    return host, junction_path


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
                LOG.info('No rpm info found for %(pkg)s package.', {
                    'pkg': self.PACKAGE_NAME})
                return False
            parts = out.split()
            self._version = parts[0]
            self._release = parts[1]
            self._vendor = ' '.join(parts[2::])
            return True
        except Exception as e:
            LOG.info('Could not run rpm command: %(msg)s.', {'msg': e})
            return False

    # ubuntu, mirantis on ubuntu
    def _update_info_from_dpkg(self):
        LOG.debug('Trying dpkg-query command.')
        try:
            _vendor = None
            out, err = putils.execute("dpkg-query", "-W", "-f='${Version}'",
                                      self.PACKAGE_NAME)
            if not out:
                LOG.info('No dpkg-query info found for %(pkg)s package.',
                         {'pkg': self.PACKAGE_NAME})
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
            LOG.info('Could not run dpkg-query command: %(msg)s.', {
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


class Features(object):

    def __init__(self):
        self.defined_features = set()

    def add_feature(self, name, supported=True, min_version=None):
        if not isinstance(supported, bool):
            raise TypeError("Feature value must be a bool type.")
        self.defined_features.add(name)
        setattr(self, name, FeatureState(supported, min_version))

    def __getattr__(self, name):
        # NOTE(cknight): Needed to keep pylint happy.
        raise AttributeError


class FeatureState(object):

    def __init__(self, supported=True, minimum_version=None):
        """Represents the current state of enablement for a Feature

        :param supported: True if supported, false otherwise
        :param minimum_version: The minimum version that this feature is
        supported at
        """
        self.supported = supported
        self.minimum_version = minimum_version

    def __nonzero__(self):
        """Allow a FeatureState object to be tested for truth value

        :returns: True if the feature is supported, otherwise False
        """
        return self.supported

    def __bool__(self):
        """py3 Allow a FeatureState object to be tested for truth value

        :returns: True if the feature is supported, otherwise False
        """
        return self.supported


class BitSet(object):
    def __init__(self, value=0):
        self._value = value

    def set(self, bit):
        self._value |= 1 << bit
        return self

    def unset(self, bit):
        self._value &= ~(1 << bit)
        return self

    def is_set(self, bit):
        return self._value & 1 << bit

    def __and__(self, other):
        self._value &= other
        return self

    def __or__(self, other):
        self._value |= other
        return self

    def __invert__(self):
        self._value = ~self._value
        return self

    def __xor__(self, other):
        self._value ^= other
        return self

    def __lshift__(self, other):
        self._value <<= other
        return self

    def __rshift__(self, other):
        self._value >>= other
        return self

    def __int__(self):
        return self._value

    def __str__(self):
        return bin(self._value)

    def __repr__(self):
        return str(self._value)

    def __eq__(self, other):
        return (isinstance(other, self.__class__) and self._value ==
                other._value) or self._value == int(other)

    def __ne__(self, other):
        return not self.__eq__(other)
