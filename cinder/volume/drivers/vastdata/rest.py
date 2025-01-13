# Copyright 2025 VAST Data Inc.
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
from abc import ABC
import json
import pprint
import random
import textwrap

import cachetools
import distro
from oslo_log import log as logging
from oslo_utils import versionutils
from packaging import version as packaging_version
import requests
from requests import cookies
from tabulate import tabulate

from cinder import exception
from cinder.i18n import _
import cinder.utils as cinder_utils
import cinder.volume.drivers.vastdata.utils as vast_utils


LOG = logging.getLogger(__name__)

USER_AGENT_BASE = "OpenStack Cinder"


class VastApiException(exception.VolumeBackendAPIException):
    message = _("Rest API error: %(reason)s.")


class VastApiRetry(exception.VolumeBackendAPIException):
    message = _("Rest API retry: %(reason)s.")


class NoCookiesJar(cookies.RequestsCookieJar):
    def set(self, name, value, **kwargs):
        return None

    def set_cookie(self, cookie, *args, **kwargs):
        return


class Session(requests.Session):

    def __init__(
        self,
        host,
        username,
        password,
        api_token,
        ssl_verify,
        plugin_version,
        rest_api_version="v4",
    ):
        super().__init__()
        self.base_url = f"https://{host.strip('/')}/api/{rest_api_version}"
        self.ssl_verify = ssl_verify
        self.username = username
        self.password = password
        self.token = api_token
        self.cookies = NoCookiesJar()
        self.headers["Accept"] = "application/json"
        self.headers["Content-Type"] = "application/json"
        user_agent = "%(base)s %(class)s/%(version)s (%(platform)s)" % {
            'base': USER_AGENT_BASE,
            'class': self.__class__.__name__,
            'version': plugin_version,
            'platform': distro.name(pretty=True)
        }
        self.headers["User-Agent"] = user_agent
        if self.token:
            LOG.info("VMS session is using API token authentication.")
            self.headers["authorization"] = f"Api-Token {self.token}"
        else:
            LOG.info(
                "VMS session is using username/password authentication"
                " (Bearer token will be acquired)."
            )
            # Will be updated on the first request
            self.headers["authorization"] = "Bearer #"

        if not ssl_verify:
            import urllib3

            urllib3.disable_warnings()

    def refresh_auth_token(self):
        try:
            resp = super().request(
                "POST",
                f"{self.base_url}/token/",
                verify=self.ssl_verify,
                timeout=30,
                json={"username": self.username, "password": self.password},
            )
            resp.raise_for_status()
            token = resp.json()["access"]
            self.headers["authorization"] = f"Bearer {token}"
        except ConnectionError as e:
            raise VastApiException(
                reason=f"The vms on the designated host {self.base_url} "
                f"cannot be accessed. Please verify the specified endpoint. "
                f"origin error: {e}"
            )

    @cinder_utils.retry(
        retry_param=VastApiRetry,
        retries=3,
        interval=0.2,
        backoff_rate=0.2,
    )
    def request(
        self,
        verb,
        api_method,
        resource_factory_name,
        params=None,
        **kwargs,
    ):
        verb = verb.upper()
        api_method = api_method.strip("/")
        url = f"{self.base_url}/{api_method}/"
        log_pref = f"\n[{verb}] {url}"
        resource_factory = VAST_RESOURCES_FACTORY.get(resource_factory_name)
        assert resource_factory, \
            (f"Resource factory not found for {api_method}. "
             f"Declare new resource in VAST_RESOURCES_FACTORY.")

        if params:
            log_result = params.pop("log_result", True)
        elif kwargs:
            log_result = kwargs.pop("log_result", True)
        else:
            log_result = True

        if "data" in kwargs:
            kwargs["data"] = json.dumps(kwargs["data"])

        if log_result and (params or kwargs):
            payload = dict(kwargs, params=params)
            formatted_request = textwrap.indent(
                pprint.pformat(payload), prefix="|  "
            )
            LOG.debug("%s >>>:\n%s\n", log_pref, formatted_request)
        else:
            LOG.debug("%s >>> (request)", log_pref)

        ret = super().request(
            verb, url, verify=self.ssl_verify, params=params, **kwargs
        )
        # No refresh for token based auth. Token should be long-lived.
        if ret.status_code == 403 and not self.token:
            self.refresh_auth_token()
            raise VastApiRetry(
                reason=f"refreshing token: reason: {ret.text}",
            )

        if ret.status_code in (400, 503) and ret.text:
            raise VastApiException(reason=ret.text)

        try:
            ret.raise_for_status()
        except Exception as exc:
            raise VastApiException(reason=str(exc))

        if ret.content:
            ret = resource_factory.create_with_data(ret.json())
        else:
            ret = None
        if log_result and ret:
            formatted_response = textwrap.indent(ret.render(), prefix="| ")
            LOG.debug("%s <<<:\n%s\n", log_pref, formatted_response)
        else:
            LOG.debug("%s <<< (response)", log_pref)
        return ret


class VastResourceCollection(list):
    def __repr__(self):
        return self.render(short=True)

    __str__ = __repr__

    def render(self, short=False):
        """Render the entire collection."""
        if self:
            return (
                "\n[\n"
                + "\n".join(entry.render(short=short) for entry in self)
                + "\n]"
            )
        else:
            return "[]"


class VastResourceEntry(vast_utils.Bunch):
    def __init__(
        self,
        name: str,
        printable_attrs=(),
        prepare_data_cb=None,
    ):
        super().__init__()

        # Assign private attributes (e.g., _name)
        # to avoid them being printed in JSON format
        self._name = name
        self._printable_attrs = sorted(set(printable_attrs))
        self._prepare_data_cb = prepare_data_cb

    def to_dict(self):
        """Convert the VastResourceEntry to a dictionary"""
        return {
            key: value
            for key, value in self.items()
            if not key.startswith("_")
        }

    def render(self, short=False):
        attrs_table = [
            [attr, repr(self.get(attr))]
            for attr in self._printable_attrs
            if not attr.startswith("_")
        ]
        # Prepare the remaining attributes (those not in `printable_attrs`)
        remaining_attrs = {
            k: v
            for k, v in self.items()
            if k not in self._printable_attrs and not k.startswith("_")
        }
        if remaining_attrs and not short:
            # Pretty-print remaining attributes as JSON
            remaining_attrs_lines = (
                pprint.pformat(remaining_attrs)
                .splitlines()
            )
            # Add a row with <<remaining attrs>>
            # as the key and the multi-line JSON as the value
            attrs_table.append(
                ["<<remaining attrs>>", remaining_attrs_lines[0]]
            )
            # Add subsequent rows with an empty key for the remaining lines
            for line in remaining_attrs_lines[1:]:
                attrs_table.append(["", line])
        attrs_table_str = tabulate(
            attrs_table,
            headers=["attr", "value"],
            tablefmt="psql",
        )
        return f"{self._name}:\n{attrs_table_str}"

    def __getattr__(self, name):
        """Allow attribute access like dictionary keys."""
        if name in self:
            return self[name]
        raise AttributeError(
            f"'{self.__class__.__name__}' object has no attribute '{name}'"
        )

    def __getitem__(self, key):
        """Allow item[key] syntax to work"""
        return super().__getitem__(key)

    def __setattr__(self, name, value):
        """Set the item like a dict entry"""
        self[name] = value

    def __delattr__(self, name):
        """Delete the item like a dict entry"""
        if name in self:
            del self[name]

    def __getstate__(self):
        """Return the state for serialization"""
        return dict(self)

    def __setstate__(self, state):
        """Restore the state from serialization"""
        self.update(state)

    def create_with_data(self, data):
        """Create a new instance of the resource"""
        # Handle pagination envelope (dict with 'results' and 'count')
        # This provides idempotent handling for both paginated and
        # non-paginated responses from the API
        if isinstance(data, dict) and "results" in data and "count" in data:
            # This is a paginated response, extract the results array
            data = data['results']

        # If data is a dictionary,
        # create a new instance with additional attributes
        if isinstance(data, dict):
            if self._prepare_data_cb:
                data = self._prepare_data_cb(data)
                if isinstance(data, (list, tuple, set)):
                    return VastResourceCollection(
                        self.create_with_data(entry) for entry in data if entry
                    )
            if not data:
                return
            new_instance = self.__class__(
                name=self._name,
                printable_attrs=self._printable_attrs,
            )
            new_instance.update(data)  # Update with additional data
            return new_instance

        # If data is a list, create a list of new instances
        elif isinstance(data, (list, tuple, set)):
            return VastResourceCollection(
                self.create_with_data(entry) for entry in data if entry
            )
        else:
            raise TypeError(
                f"Expected data to be either"
                f" a dict or a list, got {type(data)}"
            )


VAST_RESOURCES_FACTORY = {}


class VastResource(ABC):
    resource_name = None
    printable_attrs = ("name", "id")
    cached_methods = ()

    def __init__(self, rest):
        self.rest = rest  # For intercommunication between resources.
        self.session = rest.session
        VAST_RESOURCES_FACTORY[self.resource_name] = VastResourceEntry(
            name=self.__class__.__name__,
            printable_attrs=self.printable_attrs,
            prepare_data_cb=self._prepare_data_cb,
        )
        for method_name, ttl in self.cached_methods:
            setattr(
                self, method_name, self._to_cached_method(method_name, ttl)
            )

    def list(self, **params):
        """Get list of entries with optional filtering params"""
        return self.session.get(
            self.resource_name,
            params=params,
            resource_factory_name=self.resource_name,
        )

    def create(self, **params):
        """Create new entry with provided params"""
        return self.session.post(
            self.resource_name,
            data=params,
            resource_factory_name=self.resource_name,
        )

    def update(self, entry_id, **params):
        """Update entry by id with provided params"""
        return self.session.patch(
            f"{self.resource_name}/{entry_id}",
            data=params,
            resource_factory_name=self.resource_name,
        )

    def delete(self, **params):
        """Delete entry by provided params. Skip if entry not found."""
        entry = self.one(**params)
        if not entry:
            resource = self.__class__.__name__.lower()
            serialized_params = json.dumps(params, separators=(",", ":"))
            LOG.warning(
                "%r not found for params %s, skipping delete",
                resource, serialized_params
            )
            return
        return self.delete_by_id(entry["id"])

    def delete_by_id(self, entry_id, **params):
        """Delete entry by id"""
        return self.session.delete(
            f"{self.resource_name}/{entry_id}",
            resource_factory_name=self.resource_name,
            **params,
        )

    def one(self, fail_if_missing=False, **params):
        """Retrieve a single entry by provided filter parameters.

        Raises exception If no entry is found and `fail_if_missing` is True,
        or if multiple entries are found.
        """
        entries = self.list(**params)
        resource = self.__class__.__name__.lower()
        if not entries:
            if fail_if_missing:
                serialized_params = json.dumps(params, separators=(",", ":"))
                raise VastApiException(
                    reason=f"No {resource!r} "
                           f"found for params {serialized_params}"
                )
            return
        if len(entries) > 1:
            serialized_params = json.dumps(params, separators=(",", ":"))
            raise VastApiException(
                reason=f"Too many '{resource}s' "
                f"found for params {serialized_params}: {entries}"
            )
        return entries[0]

    def ensure(self, name, **params):
        entry = self.one(name=name)
        if not entry:
            entry = self.create(name=name, **params)
        return entry

    def get(self, entry_id, **params):
        """Get single entry by id"""
        return self.session.get(
            f"{self.resource_name}/{entry_id}",
            params=params,
            resource_factory_name=self.resource_name,
        )

    def _to_cached_method(self, method_name, ttl):
        """Wrap method with caching decorator"""
        try:
            method = getattr(self, method_name)
        except AttributeError:
            raise ValueError(f"Method '{method_name}' does not exist.")
        return cachetools.cached(
            cache=cachetools.TTLCache(ttl=ttl, maxsize=1)
        )(method)

    def _prepare_data_cb(self, data):
        """Prepare data callback for create_with_data method"""
        return data


class Version(VastResource):
    resource_name = "versions"
    printable_attrs = ("sys_version",)

    def get_sw_version(self):
        """Get VMS software version."""
        version = packaging_version.parse(
            self.list(status="success")[0].sys_version.replace("-", ".")
        )
        return f"{version.major}.{version.minor}.{version.micro}"

    def check_min_vast_version(self, min_version):
        """Check compatibility with VAST cluster."""
        vast_version = self.get_sw_version()
        if not versionutils.is_compatible(min_version, vast_version):
            raise VastApiException(
                reason=f"VAST version {vast_version} is not supported. "
                f"Required version is >= {min_version} "
                f"Found version is {vast_version}"
            )


class Snapshot(VastResource):
    resource_name = "snapshots"
    printable_attrs = ("id", "name", "path")

    def clone_volume(
            self,
            snapshot_id,
            target_subsystem_id,
            target_volume_path
    ):
        """Clone a snapshot to a target volume.

        This method creates a new volume by cloning
        an existing snapshot and associates it
        with the specified subsystem and volume path.
        """
        data = {
            "target_subsystem_id": target_subsystem_id,
            "target_volume_path": target_volume_path,
        }
        return self.session.post(
            f"{self.resource_name}/{snapshot_id}/clone_volume/",
            data=data,
            resource_factory_name=self.rest.volumes.resource_name,
        )

    def has_not_finished_streams(self, snapshot_id):
        """Check if snapshot has unfinished global snapshot streams.

        Returns True if there are any global snapshot streams associated
        with the given snapshot ID that are not in 'finished' state.
        """
        resp = self.rest.globalsnapstreams.list(
            loanee_snapshot__id=snapshot_id, page_size=10,
        )
        return any(
            s.status.get("state", "").lower() != "finished"
            for s in resp
        )


class View(VastResource):
    resource_name = "views"
    cached_methods = (("get_subsystem", 600), ("get_subsystem_by_id", 600))
    printable_attrs = ("id", "name", "tenant_id", "nqn")

    def get_subsystem(self, subsystem, tenant_name=None):
        """Get BLOCK type view by provided name."""
        filter_params = dict(name=subsystem, fail_if_missing=True)
        if tenant_name:
            filter_params["tenant_name"] = tenant_name
        view = self.one(**filter_params)
        assert "BLOCK" in view.protocols
        return view

    def get_subsystem_by_id(self, entry_id):
        """Get BLOCK type view by provided id."""
        view = self.get(entry_id)
        assert "BLOCK" in view.protocols
        return view


class VipPool(VastResource):
    resource_name = "vippools"
    printable_attrs = ("id", "name", "ip_ranges")
    cached_methods = (("get_vips", 600),)

    def get_vips(self, vip_pool_name, tenant_id=None):
        """Get vip by provided vip_pool_name.

        tenant_id is optional argument for validation.
        Returns:
            Random vip ip from provided vip pool.
        """
        vippool = self.one(name=vip_pool_name, fail_if_missing=True)
        if isinstance(tenant_id, str):
            tenant_id = int(tenant_id)
        if tenant_id and vippool.tenant_id and vippool.tenant_id != tenant_id:
            raise VastApiException(
                f"Pool {vip_pool_name} belongs to tenant with id"
                f" {vippool.tenant_id} but {tenant_id=} was requested"
            )
        vips = vast_utils.generate_ip_range(vippool.ip_ranges)
        if not vips:
            raise VastApiException(
                f"Pool {vip_pool_name} has no available vips"
            )
        return vips

    def get_vip(self, vip_pool_name, tenant_id=None):
        return random.choice(self.get_vips(vip_pool_name, tenant_id))


class BlockHost(VastResource):
    resource_name = "blockhosts"
    printable_attrs = ("id", "name", "nqn", "volumes")

    def ensure(self, name, tenant_id, nqn):
        if blockhost := self.one(name=name, tenant_id=tenant_id):
            return blockhost
        data = dict(
            name=name,
            tenant_id=tenant_id,
            os_type="LINUX",
            ana="OPTIMIZED",
            connectivity_type="tcp",
            nqn=nqn,
        )
        return self.create(**data)


class Volume(VastResource):
    resource_name = "volumes"
    printable_attrs = (
        "id", "name", "nguid", "subsystem_name", "size"
    )

    def delete_by_id(self, entry_id):
        """Delete entry by id"""
        return super().delete_by_id(
            entry_id=entry_id,
            params={"force": True}
        )


class BlockHostMapping(VastResource):
    resource_name = "blockhostvolumes"
    printable_attrs = ("volume", "block_host")

    def map(self, volume_id, host_id):
        data = {
            "pairs_to_add": [{"host_id": host_id, "volume_id": volume_id}]
        }
        task = self.session.patch(
            f"{self.resource_name}/bulk", data=data,
            resource_factory_name=self.rest.vtasks.resource_name,
        )
        return self.rest.vtasks.wait_task(task.id)

    def ensure_map(self, volume_id, host_id):
        if not self.one(volume__id=volume_id, block_host__id=host_id):
            return self.map(volume_id, host_id)

    def unmap(self, volume_id, host_id):
        data = {
            "pairs_to_remove": [{"host_id": host_id, "volume_id": volume_id}]
        }
        task = self.session.patch(
            f"{self.resource_name}/bulk",
            data=data,
            resource_factory_name=self.rest.vtasks.resource_name,
        )
        return self.rest.vtasks.wait_task(task.id)

    def ensure_unmap(self, **params):
        if mapping := self.one(**params):
            return self.unmap(
                volume_id=mapping.volume["id"],
                host_id=mapping.block_host["id"],
            )


class VTask(VastResource):
    resource_name = "vtasks"
    printable_attrs = ("name", "guid", "state")

    def wait_task(self, task_id, verbose=False):
        """Waits for a specific task to start and complete execution"""
        task_line = 0

        def is_task_complete(task_id):
            """Checks if the task is complete."""
            nonlocal task_line
            task = self.get(
                task_id,
                log_result=False,
            )
            if verbose:
                for line in task.messages[task_line:]:
                    LOG.debug(line)
            task_line = len(task.messages)
            if task.state.lower() == "completed":
                return task
            elif task.state.lower() != "running":
                raise VastApiRetry(
                    reason=f"Task {task.name} "
                           f"failed with id {task.id}: {task.messages[-1]}"
                )
            else:
                raise VastApiRetry(
                    reason=f"Task {task.name} with id "
                           f"{task.id} is still running, timeout occurred."
                )

        # Retry logic for task completion
        @cinder_utils.retry(
            retry_param=VastApiRetry,
            retries=30,
            interval=1,
            backoff_rate=1,
        )
        def fetch_completed_task():
            """Attempts to monitor the task and check if it's complete."""
            return is_task_complete(task_id)

        # Wait for task completion with retries
        return fetch_completed_task()

    def _prepare_data_cb(self, data):
        """Prepare data callback for create_with_data method"""
        return data.get("async_task", data)


class CapacityMetrics(VastResource):
    resource_name = "monitors"
    printable_attrs = (
        "logical_space_in_use",
        "physical_space_in_use",
        "logical_space",
        "physical_space",
        "drr",
    )

    def get(self, metrics=None, object_type="cluster", time_frame="1m"):
        """Get capacity metrics for the cluster"""
        if not metrics:
            metrics = [
                "Capacity,drr",
                "Capacity,logical_space",
                "Capacity,logical_space_in_use",
                "Capacity,physical_space",
                "Capacity,physical_space_in_use",
            ]
        params = dict(
            prop_list=metrics,
            object_type=object_type,
            time_frame=time_frame,
        )
        return self.session.get(
            f"{self.resource_name}/ad_hoc_query",
            params=params,
            resource_factory_name=self.resource_name,
        )

    def _prepare_data_cb(self, data):
        """Prepare data callback for create_with_data method"""
        metrics = data["data"]
        if not data:
            return
        last_sample = metrics[-1]
        prop_list = data["prop_list"]
        return {
            refined_name: value
            for name, value in zip(prop_list, last_sample)
            if (refined_name := name.partition(",")[-1])
        }


class GlobalSnapshotStream(VastResource):
    resource_name = "globalsnapstreams"

    def stop_snapshot_stream(self, snapshot_stream_id):
        return self.session.patch(
            f"{self.resource_name}/{snapshot_stream_id}/stop",
            resource_factory_name=self.rest.vtasks.resource_name,
        )

    def ensure(self, name, snapshot_id, tenant_id, destination_path):
        if not (snapshot_stream := self.one(name=name)):
            data = dict(
                loanee_root_path=destination_path,
                name=name,
                enabled=True,
                loanee_tenant_id=tenant_id,  # target tenant_id
            )
            snapshot_stream = self.session.post(
                f"snapshots/{snapshot_id}/clone/",
                resource_factory_name=self.resource_name,
                data=data,
            )
        return snapshot_stream

    def ensure_snapshot_stream_deleted(self, volume_id):
        """Stop global snapshot stream in case it is not finished.

        Snapshots with expiration time
        will be deleted as soon as snapshot stream is stopped.
        """
        if snapshot_stream := self.one(name__endswith=volume_id):
            state = snapshot_stream["status"].get("state", "").lower()
            if state != "finished":
                task = self.stop_snapshot_stream(snapshot_stream["id"])
                self.rest.vtasks.wait_task(task["id"])
            self.delete_by_id(
                entry_id=snapshot_stream["id"],
                data={"remove_dir": True}
            )


class RestApi:

    def __init__(self, configuration, plugin_version):
        get_config_value = configuration.safe_get
        username = get_config_value("san_login")
        password = get_config_value("san_password")
        api_token = get_config_value("vast_api_token")
        rest_host = get_config_value("san_ip")
        rest_port = get_config_value("san_api_port")
        ssl_cert_path = (
            get_config_value("driver_ssl_cert_path")
            or None
        )
        verify = (
            get_config_value("driver_ssl_cert_verify")
            or False
        )
        if verify and ssl_cert_path:
            verify = ssl_cert_path

        if rest_port:
            rest_host = f"{rest_host}:{rest_port}"
        self.session = Session(
            host=rest_host,
            username=username,
            password=password,
            api_token=api_token,
            ssl_verify=verify,
            plugin_version=plugin_version,
        )
        self.versions = Version(self)
        self.views = View(self)
        self.snapshots = Snapshot(self)
        self.vip_pools = VipPool(self)
        self.vtasks = VTask(self)
        self.volumes = Volume(self)
        self.blockhosts = BlockHost(self)
        self.capacity_metrics = CapacityMetrics(self)
        self.globalsnapstreams = GlobalSnapshotStream(self)
        self.blockhostmappings = BlockHostMapping(self)

    def do_setup(self):
        """Initial setup for the VAST REST API client."""
        if not self.session.token:
            self.session.refresh_auth_token()
        self.versions.check_min_vast_version(
            min_version=vast_utils.VAST_MIN_VERSION
        )
