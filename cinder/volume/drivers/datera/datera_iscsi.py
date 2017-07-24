# Copyright 2017 Datera
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

import time
import uuid

from eventlet.green import threading
from oslo_config import cfg
from oslo_log import log as logging
import six

from cinder import exception
from cinder.i18n import _
from cinder import utils
from cinder.volume import configuration
from cinder.volume.drivers.san import san

import cinder.volume.drivers.datera.datera_api2 as api2
import cinder.volume.drivers.datera.datera_api21 as api21
import cinder.volume.drivers.datera.datera_common as datc


LOG = logging.getLogger(__name__)

d_opts = [
    cfg.StrOpt('datera_api_port',
               default='7717',
               help='Datera API port.'),
    cfg.StrOpt('datera_api_version',
               default='2',
               deprecated_for_removal=True,
               help='Datera API version.'),
    cfg.IntOpt('datera_503_timeout',
               default='120',
               help='Timeout for HTTP 503 retry messages'),
    cfg.IntOpt('datera_503_interval',
               default='5',
               help='Interval between 503 retries'),
    cfg.BoolOpt('datera_debug',
                default=False,
                help="True to set function arg and return logging"),
    cfg.BoolOpt('datera_debug_replica_count_override',
                default=False,
                help="ONLY FOR DEBUG/TESTING PURPOSES\n"
                     "True to set replica_count to 1"),
    cfg.StrOpt('datera_tenant_id',
               default=None,
               help="If set to 'Map' --> OpenStack project ID will be mapped "
                    "implicitly to Datera tenant ID\n"
                    "If set to 'None' --> Datera tenant ID will not be used "
                    "during volume provisioning\n"
                    "If set to anything else --> Datera tenant ID will be the "
                    "provided value"),
    cfg.BoolOpt('datera_disable_profiler',
                default=False,
                help="Set to True to disable profiling in the Datera driver"),
]


CONF = cfg.CONF
CONF.import_opt('driver_use_ssl', 'cinder.volume.driver')
CONF.register_opts(d_opts, group=configuration.SHARED_CONF_GROUP)


@six.add_metaclass(utils.TraceWrapperWithABCMetaclass)
class DateraDriver(san.SanISCSIDriver, api2.DateraApi, api21.DateraApi):

    """The OpenStack Datera Driver

    Version history:
        * 1.0 - Initial driver
        * 1.1 - Look for lun-0 instead of lun-1.
        * 2.0 - Update For Datera API v2
        * 2.1 - Multipath, ACL and reorg
        * 2.2 - Capabilites List, Extended Volume-Type Support
                Naming convention change,
                Volume Manage/Unmanage support
        * 2.3 - Templates, Tenants, Snapshot Polling,
                2.1 Api Version Support, Restructure
        * 2.3.1 - Scalability bugfixes
        * 2.3.2 - Volume Placement, ACL multi-attach bugfix
        * 2.4.0 - Fast Retype Support
    """
    VERSION = '2.4.0'

    CI_WIKI_NAME = "datera-ci"

    HEADER_DATA = {'Datera-Driver': 'OpenStack-Cinder-{}'.format(VERSION)}

    def __init__(self, *args, **kwargs):
        super(DateraDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(d_opts)
        self.username = self.configuration.san_login
        self.password = self.configuration.san_password
        self.cluster_stats = {}
        self.datera_api_token = None
        self.interval = self.configuration.datera_503_interval
        self.retry_attempts = (self.configuration.datera_503_timeout /
                               self.interval)
        self.driver_prefix = str(uuid.uuid4())[:4]
        self.datera_debug = self.configuration.datera_debug
        self.datera_api_versions = []

        if self.datera_debug:
            utils.setup_tracing(['method'])
        self.tenant_id = self.configuration.datera_tenant_id
        if self.tenant_id and self.tenant_id.lower() == 'none':
            self.tenant_id = None
        self.api_check = time.time()
        self.api_cache = []
        self.api_timeout = 0
        self.do_profile = not self.configuration.datera_disable_profiler
        self.thread_local = threading.local()

        backend_name = self.configuration.safe_get(
            'volume_backend_name')
        self.backend_name = backend_name or 'Datera'

        datc.register_driver(self)

    def do_setup(self, context):
        # If we can't authenticate through the old and new method, just fail
        # now.
        if not all([self.username, self.password]):
            msg = _("san_login and/or san_password is not set for Datera "
                    "driver in the cinder.conf. Set this information and "
                    "start the cinder-volume service again.")
            LOG.error(msg)
            raise exception.InvalidInput(msg)

        self.login()
        self._create_tenant()

    # =================

    # =================
    # = Create Volume =
    # =================

    @datc._api_lookup
    def create_volume(self, volume):
        """Create a logical volume."""
        pass

    # =================
    # = Extend Volume =
    # =================

    @datc._api_lookup
    def extend_volume(self, volume, new_size):
        pass

    # =================

    # =================
    # = Cloned Volume =
    # =================

    @datc._api_lookup
    def create_cloned_volume(self, volume, src_vref):
        pass

    # =================
    # = Delete Volume =
    # =================

    @datc._api_lookup
    def delete_volume(self, volume):
        pass

    # =================
    # = Ensure Export =
    # =================

    @datc._api_lookup
    def ensure_export(self, context, volume, connector=None):
        """Gets the associated account, retrieves CHAP info and updates."""

    # =========================
    # = Initialize Connection =
    # =========================

    @datc._api_lookup
    def initialize_connection(self, volume, connector):
        pass

    # =================
    # = Create Export =
    # =================

    @datc._api_lookup
    def create_export(self, context, volume, connector):
        pass

    # =================
    # = Detach Volume =
    # =================

    @datc._api_lookup
    def detach_volume(self, context, volume, attachment=None):
        pass

    # ===================
    # = Create Snapshot =
    # ===================

    @datc._api_lookup
    def create_snapshot(self, snapshot):
        pass

    # ===================
    # = Delete Snapshot =
    # ===================

    @datc._api_lookup
    def delete_snapshot(self, snapshot):
        pass

    # ========================
    # = Volume From Snapshot =
    # ========================

    @datc._api_lookup
    def create_volume_from_snapshot(self, volume, snapshot):
        pass

    # ==========
    # = Retype =
    # ==========

    @datc._api_lookup
    def retype(self, ctxt, volume, new_type, diff, host):
        """Convert the volume to be of the new type.

        Returns a boolean indicating whether the retype occurred.

        :param ctxt: Context
        :param volume: A dictionary describing the volume to migrate
        :param new_type: A dictionary describing the volume type to convert to
        :param diff: A dictionary with the difference between the two types
        :param host: A dictionary describing the host to migrate to, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities (Not Used).
        """
        pass

    # ==========
    # = Manage =
    # ==========

    @datc._api_lookup
    def manage_existing(self, volume, existing_ref):
        """Manage an existing volume on the Datera backend

        The existing_ref must be either the current name or Datera UUID of
        an app_instance on the Datera backend in a colon separated list with
        the storage instance name and volume name.  This means only
        single storage instances and single volumes are supported for
        managing by cinder.

        Eg.

        (existing_ref['source-name'] ==
             tenant:app_inst_name:storage_inst_name:vol_name)

        if using Datera 2.1 API

        or

        (existing_ref['source-name'] ==
             app_inst_name:storage_inst_name:vol_name)

        if using 2.0 API

        :param volume:       Cinder volume to manage
        :param existing_ref: Driver-specific information used to identify a
                             volume
        """
        pass

    # ===================
    # = Manage Get Size =
    # ===================

    @datc._api_lookup
    def manage_existing_get_size(self, volume, existing_ref):
        """Get the size of an unmanaged volume on the Datera backend

        The existing_ref must be either the current name or Datera UUID of
        an app_instance on the Datera backend in a colon separated list with
        the storage instance name and volume name.  This means only
        single storage instances and single volumes are supported for
        managing by cinder.

        Eg.

        existing_ref == app_inst_name:storage_inst_name:vol_name

        :param volume:       Cinder volume to manage
        :param existing_ref: Driver-specific information used to identify a
                             volume on the Datera backend
        """
        pass

    # =========================
    # = Get Manageable Volume =
    # =========================

    @datc._api_lookup
    def get_manageable_volumes(self, cinder_volumes, marker, limit, offset,
                               sort_keys, sort_dirs):
        """List volumes on the backend available for management by Cinder.

        Returns a list of dictionaries, each specifying a volume in the host,
        with the following keys:

        - reference (dictionary): The reference for a volume, which can be
          passed to 'manage_existing'.
        - size (int): The size of the volume according to the storage
          backend, rounded up to the nearest GB.
        - safe_to_manage (boolean): Whether or not this volume is safe to
          manage according to the storage backend. For example, is the volume
          in use or invalid for any reason.
        - reason_not_safe (string): If safe_to_manage is False, the reason why.
        - cinder_id (string): If already managed, provide the Cinder ID.
        - extra_info (string): Any extra information to return to the user

        :param cinder_volumes: A list of volumes in this host that Cinder
                               currently manages, used to determine if
                               a volume is manageable or not.
        :param marker:    The last item of the previous page; we return the
                          next results after this value (after sorting)
        :param limit:     Maximum number of items to return
        :param offset:    Number of items to skip after marker
        :param sort_keys: List of keys to sort results by (valid keys are
                          'identifier' and 'size')
        :param sort_dirs: List of directions to sort by, corresponding to
                          sort_keys (valid directions are 'asc' and 'desc')
        """
        pass

    # ============
    # = Unmanage =
    # ============

    @datc._api_lookup
    def unmanage(self, volume):
        """Unmanage a currently managed volume in Cinder

        :param volume:       Cinder volume to unmanage
        """
        pass

    # ================
    # = Volume Stats =
    # ================

    @datc._api_lookup
    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        If 'refresh' is True, run update first.
        The name is a bit misleading as
        the majority of the data here is cluster
        data.
        """
        pass

    # =========
    # = Login =
    # =========

    @datc._api_lookup
    def login(self):
        pass

    # =======
    # = QoS =
    # =======

    def _update_qos(self, resource, policies):
        url = datc.URL_TEMPLATES['vol_inst'](
            policies['default_storage_name'],
            policies['default_volume_name']) + '/performance_policy'
        url = url.format(datc._get_name(resource['id']))
        type_id = resource.get('volume_type_id', None)
        if type_id is not None:
            # Filter for just QOS policies in result. All of their keys
            # should end with "max"
            fpolicies = {k: int(v) for k, v in
                         policies.items() if k.endswith("max")}
            # Filter all 0 values from being passed
            fpolicies = dict(filter(lambda _v: _v[1] > 0, fpolicies.items()))
            if fpolicies:
                self._issue_api_request(url, 'post', body=fpolicies,
                                        api_version='2')

    def _get_lunid(self):
        return 0

    # ============================
    # = Volume-Types/Extra-Specs =
    # ============================

    def _init_vendor_properties(self):
        """Create a dictionary of vendor unique properties.

        This method creates a dictionary of vendor unique properties
        and returns both created dictionary and vendor name.
        Returned vendor name is used to check for name of vendor
        unique properties.

        - Vendor name shouldn't include colon(:) because of the separator
          and it is automatically replaced by underscore(_).
          ex. abc:d -> abc_d
        - Vendor prefix is equal to vendor name.
          ex. abcd
        - Vendor unique properties must start with vendor prefix + ':'.
          ex. abcd:maxIOPS

        Each backend driver needs to override this method to expose
        its own properties using _set_property() like this:

        self._set_property(
            properties,
            "vendorPrefix:specific_property",
            "Title of property",
            _("Description of property"),
            "type")

        : return dictionary of vendor unique properties
        : return vendor name

        prefix: DF --> Datera Fabric
        """

        properties = {}

        self._set_property(
            properties,
            "DF:placement_mode",
            "Datera Volume Placement",
            _("'single_flash' for single-flash-replica placement, "
              "'all_flash' for all-flash-replica placement, "
              "'hybrid' for hybrid placement"),
            "string",
            default="hybrid")

        self._set_property(
            properties,
            "DF:round_robin",
            "Datera Round Robin Portals",
            _("True to round robin the provided portals for a target"),
            "boolean",
            default=False)

        if self.configuration.get('datera_debug_replica_count_override'):
            replica_count = 1
        else:
            replica_count = 3
        self._set_property(
            properties,
            "DF:replica_count",
            "Datera Volume Replica Count",
            _("Specifies number of replicas for each volume. Can only be "
              "increased once volume is created"),
            "integer",
            minimum=1,
            default=replica_count)

        self._set_property(
            properties,
            "DF:acl_allow_all",
            "Datera ACL Allow All",
            _("True to set acl 'allow_all' on volumes created.  Cannot be "
              "changed on volume once set"),
            "boolean",
            default=False)

        self._set_property(
            properties,
            "DF:ip_pool",
            "Datera IP Pool",
            _("Specifies IP pool to use for volume"),
            "string",
            default="default")

        self._set_property(
            properties,
            "DF:template",
            "Datera Template",
            _("Specifies Template to use for volume provisioning"),
            "string",
            default="")

        # ###### QoS Settings ###### #
        self._set_property(
            properties,
            "DF:read_bandwidth_max",
            "Datera QoS Max Bandwidth Read",
            _("Max read bandwidth setting for volume qos, "
              "use 0 for unlimited"),
            "integer",
            minimum=0,
            default=0)

        self._set_property(
            properties,
            "DF:default_storage_name",
            "Datera Default Storage Instance Name",
            _("The name to use for storage instances created"),
            "string",
            default="storage-1")

        self._set_property(
            properties,
            "DF:default_volume_name",
            "Datera Default Volume Name",
            _("The name to use for volumes created"),
            "string",
            default="volume-1")

        self._set_property(
            properties,
            "DF:write_bandwidth_max",
            "Datera QoS Max Bandwidth Write",
            _("Max write bandwidth setting for volume qos, "
              "use 0 for unlimited"),
            "integer",
            minimum=0,
            default=0)

        self._set_property(
            properties,
            "DF:total_bandwidth_max",
            "Datera QoS Max Bandwidth Total",
            _("Max total bandwidth setting for volume qos, "
              "use 0 for unlimited"),
            "integer",
            minimum=0,
            default=0)

        self._set_property(
            properties,
            "DF:read_iops_max",
            "Datera QoS Max iops Read",
            _("Max read iops setting for volume qos, "
              "use 0 for unlimited"),
            "integer",
            minimum=0,
            default=0)

        self._set_property(
            properties,
            "DF:write_iops_max",
            "Datera QoS Max IOPS Write",
            _("Max write iops setting for volume qos, "
              "use 0 for unlimited"),
            "integer",
            minimum=0,
            default=0)

        self._set_property(
            properties,
            "DF:total_iops_max",
            "Datera QoS Max IOPS Total",
            _("Max total iops setting for volume qos, "
              "use 0 for unlimited"),
            "integer",
            minimum=0,
            default=0)
        # ###### End QoS Settings ###### #

        return properties, 'DF'
