#  Copyright (c) 2016 IBM Corporation
#  All Rights Reserved.
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
#
import functools
import gettext
import inspect
import platform
import six

from oslo_log import log as logging
from oslo_utils import timeutils

from cinder.i18n import _
from cinder import version
import cinder.volume.drivers.ibm.ibm_storage as storage
from cinder.volume.drivers.ibm.ibm_storage import strings

LOG = logging.getLogger(__name__)
gettext.install('cinder')


def get_total_seconds(td):
    return (td.microseconds + (td.seconds + td.days * 24 * 3600) * 1e6) / 1e6


def logger(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        frm = inspect.stack()[1]
        log = getattr(inspect.getmodule(frm[0]), 'LOG')
        log.debug("Enter %s()", func.__name__)
        log.debug("Args: %(args)s %(kwargs)s",
                  {'args': args, 'kwargs': kwargs})
        result = func(*args, **kwargs)
        log.debug("Exit  %s()", func.__name__)
        log.debug("Return: %s", result)
        return result
    return wrapper


def _trace_time(fnc):
    @functools.wraps(fnc)
    def wrapper(self, *args, **kwargs):
        method = fnc.__name__
        start = timeutils.utcnow()
        LOG.debug("Entered '%(method)s' at %(when)s.",
                  {'method': method, 'when': start})
        result = fnc(self, *args, **kwargs)
        current = timeutils.utcnow()
        delta = current - start
        LOG.debug(
            "Exited '%(method)s' at %(when)s, after %(seconds)f seconds.",
            {'method': method, 'when': start,
             'seconds': get_total_seconds(delta)})
        return result
    return wrapper


class IBMStorageProxy(object):
    """Base class for connecting to storage.

    Abstract Proxy between the XIV/DS8K Cinder Volume and Spectrum Accelerate
    Storage (e.g. XIV, Spectruam Accelerate, A9000, A9000R)
    """

    prefix = storage.XIV_LOG_PREFIX

    def __init__(self, storage_info, logger, exception,
                 driver=None, active_backend_id=None):
        """Initialize Proxy."""

        self.storage_info = storage_info
        self.meta = dict()
        self.logger = logger

        self.meta['exception'] = exception
        self.meta['openstack_version'] = "cinder-%s" % version.version_string()
        self.meta['stat'] = None
        self.driver = driver
        if driver is not None:
            self.full_version = "%(title)s (v%(version)s)" % {
                'title': strings.TITLE,
                'version': driver.VERSION}
        else:
            self.full_version = strings.TITLE
        self.active_backend_id = active_backend_id
        self.targets = {}
        self._read_replication_devices()
        self.meta['bypass_connection_check'] = (
            self._get_safely_from_configuration(
                storage.FLAG_KEYS['bypass_connection_check'], False))

    @_trace_time
    def setup(self, context):
        """Driver setup."""
        pass

    @_trace_time
    def create_volume(self, volume):
        """Creates a volume."""
        pass

    @_trace_time
    def ensure_export(self, context, volume):
        ctxt = context.as_dict() if hasattr(context, 'as_dict') else "Empty"
        LOG.debug("ensure_export: %(volume)s context : %(ctxt)s",
                  {'volume': volume['name'], 'ctxt': ctxt})
        return 1

    @_trace_time
    def create_export(self, context, volume):
        ctxt = context.as_dict() if hasattr(context, 'as_dict') else "Empty"
        LOG.debug("create_export: %(volume)s context : %(ctxt)s",
                  {'volume': volume['name'], 'ctxt': ctxt})

        return {}

    @_trace_time
    def delete_volume(self, volume):
        """Deletes a volume on the IBM Storage machine."""
        pass

    @_trace_time
    def remove_export(self, context, volume):
        """Remove export.

        Disconnect a volume from an attached instance
        """
        ctxt = context.as_dict() if hasattr(context, 'as_dict') else "Empty"
        LOG.debug("remove_export: %(volume)s context : %(ctxt)s",
                  {'volume': volume['name'], 'ctxt': ctxt})

    @_trace_time
    def initialize_connection(self, volume, connector):
        """Initialize connection.

        Maps the created volume to the cinder volume node,
        and returns the iSCSI/FC targets to be used in the instance
        """
        pass

    @_trace_time
    def terminate_connection(self, volume, connector):
        """Terminate connection."""
        pass

    @_trace_time
    def create_volume_from_snapshot(self, volume, snapshot):
        """create volume from snapshot."""
        pass

    @_trace_time
    def create_snapshot(self, snapshot):
        """create snapshot"""
        pass

    @_trace_time
    def delete_snapshot(self, snapshot):
        """delete snapshot."""
        pass

    @_trace_time
    def get_volume_stats(self, refresh=False):
        """get volume stats."""
        if self.meta['stat'] is None or refresh:
            self._update_stats()
        return self.meta['stat']

    @_trace_time
    def _update_stats(self):
        """fetch and update stats."""
        pass

    @_trace_time
    def check_for_export(self, context, volume_id):
        pass

    @_trace_time
    def copy_volume_to_image(self, context, volume, image_service, image_id):
        """Copy volume to image.

        Handled by ISCSiDriver
        """
        LOG.info("The copy_volume_to_image feature is not implemented.")
        raise NotImplementedError()

    @_trace_time
    def create_cloned_volume(self, volume, src_vref):
        """Create cloned volume."""
        pass

    @_trace_time
    def volume_exists(self, volume):
        """Checks if a volume exists on xiv."""
        pass

    @_trace_time
    def validate_connection(self):
        """Validates ibm_storage connection info."""
        pass

    @_trace_time
    def retype(self, ctxt, volume, new_type, diff, host):
        """Convert the volume to be of the new type."""
        pass

    @_trace_time
    def _get_bunch_from_host(
            self, connector, host_id=0, host_name=None, chap=None):
        """Get's a Bunch describing a host"""
        if not host_name:
            LOG.debug("Connector %(conn)s", {'conn': connector})
        current_host_name = host_name or storage.get_host_or_create_from_iqn(
            connector)
        initiator = connector.get('initiator', None)
        wwpns = connector.get("wwpns", [])
        if len(wwpns) == 0 and "wwnns" in connector:
            wwpns = connector.get("wwns", [])

        return {'name': current_host_name,
                'initiator': initiator,
                'id': host_id,
                'wwpns': wwpns,
                'chap': chap}

    @_trace_time
    def _get_os_type(self):
        """Gets a string representation of the current os"""
        dist = platform.dist()
        return "%s-%s-%s" % (dist[0], dist[1], platform.processor())

    def _log(self, level, message, **kwargs):
        """Wrapper around the logger"""
        to_log = _(self.prefix + message)  # NOQA
        if len(kwargs) > 0:
            to_log = to_log % kwargs
        getattr(self.logger, level)(to_log)

    def _get_exception(self):
        """Get's Cinder exception"""
        return self.meta['exception'].CinderException

    def _get_code_and_status_or_message(self, exception):
        """Returns status message

        returns a string made out of code and status if present, else message
        """

        if (getattr(exception, "code", None) is not None and
                getattr(exception, "status", None) is not None):
            return "Status: '%s', Code: %s" % (
                exception.status, exception.code)

        return six.text_type(exception)

    def _get_driver_super(self):
        """Gets the IBM Storage Drivers super class

        returns driver super class
        """
        return super(self.driver.__class__, self.driver)

    def _get_connection_type(self):
        """Get Connection Type(iscsi|fibre_channel)

        :returns: iscsi|fibre_channel
        """
        return self._get_safely_from_configuration(
            storage.CONF_KEYS['connection_type'],
            default=storage.XIV_CONNECTION_TYPE_ISCSI)

    def _is_iscsi(self):
        """Checks if connection type is iscsi"""
        connection_type = self._get_connection_type()
        return connection_type == storage.XIV_CONNECTION_TYPE_ISCSI

    def _get_management_ips(self):
        """Gets the management IP addresses from conf"""
        return self._get_safely_from_configuration(
            storage.CONF_KEYS['management_ips'],
            default='')

    def _get_chap_type(self):
        """Get CHAP Type(disabled|enabled)

        :returns: disabled|enabled
        """
        LOG.debug("_get_chap_type chap: %(chap)s",
                  {'chap': storage.CONF_KEYS['chap']})
        return self._get_safely_from_configuration(
            storage.CONF_KEYS['chap'],
            default=storage.CHAP_NONE)

    def _get_safely_from_configuration(self, key, default=None):
        """Get value of key from configuration

        Get's a key from the backend configuration if available.
        If not available returns default value
        """
        if not self.driver:
            LOG.debug("self.driver is missing")
            return default
        config_value = self.driver.configuration.safe_get(key)
        if not config_value:
            LOG.debug("missing key %(key)s ", {'key': key})
            return default
        return config_value

    # Backend_id values:
    # - The primary backend_id is marked 'default'
    # - The secondary backend_ids are the values of the targets.
    # - In most cases the given value is one of the above, but in some cases
    # it can be None. For example in failover_host, the value None means
    # that the function should select a target by itself (consider multiple
    # targets)

    def _get_primary_backend_id(self):
        return strings.PRIMARY_BACKEND_ID

    def _get_secondary_backend_id(self):
        return self._get_target()

    def _get_active_backend_id(self):
        if self.active_backend_id == strings.PRIMARY_BACKEND_ID:
            return self._get_primary_backend_id()
        else:
            return self._get_secondary_backend_id()

    def _get_inactive_backend_id(self):
        if self.active_backend_id != strings.PRIMARY_BACKEND_ID:
            return self._get_primary_backend_id()
        else:
            return self._get_secondary_backend_id()

    def _get_target_params(self, target):
        if not self.targets:
            LOG.debug("No targets available")
            return None
        try:
            params = self.targets[target]
            return params
        except Exception:
            LOG.debug("No target called '%(target)s'", {'target': target})
            return None

    def _get_target(self):
        """returns an arbitrary target if available"""
        if not self.targets:
            return None
        try:
            target = list(self.targets.keys())[0]
            return target
        except Exception:
            return None

    @_trace_time
    def _read_replication_devices(self):
        """Read replication devices from configuration

        Several replication devices are permitted.
        If an entry already exists an error is assumed.

        The format is:
        replication_device = backend_id:vendor-id-1,unique_key:val....
        """
        if not self.driver:
            return
        replication_devices = self._get_safely_from_configuration(
            'replication_device', default={})
        if not replication_devices:
            LOG.debug('No replication devices were found')
        for dev in replication_devices:
            LOG.debug('Replication device found: %(dev)s', {'dev': dev})
            backend_id = dev.get('backend_id', None)
            if backend_id is None:
                LOG.error("Replication is missing backend_id: %(dev)s",
                          {'dev': dev})
            elif self.targets.get(backend_id, None):
                LOG.error("Multiple entries for replication %(dev)s",
                          {'dev': dev})
            else:
                self.targets[backend_id] = {}
                device = self.targets[backend_id]
                for k, v in dev.items():
                    if k != 'backend_id':
                        device[k] = v
