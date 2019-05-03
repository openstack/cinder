.. Using orphan, as document is explicitly imported and not part of the toctree

:orphan:

Drivers Locking Examples
========================

This document presents an incomplete list of locks being currently used in
driver related code (main driver code, helper classes and method, etc.), to
serve as a reference to other driver developers.

.. note:: Please keep in mind that Cinder drivers may support different
  deployment options.  Some may only support running one backend on each node.
  Others may support running multiple backends in a single node.  And some may
  even support Active-Active deployments.  Therefore these references are not
  necessarily examples of how drivers achieve Active-Active.

LIO target
  - Lock scope: Node.
  - Critical section: Calls to `cinder-rtstool` CLI.
  - Lock name: `'lioadm'`.
  - Where: `_execute` method.
  - File: `cinder/volume/targets/lio.py`

NVMET target
  - Lock scope: Node.
  - Critical section: Creating or deleting NVMeOF targets operations.
  - Lock name: `'nvmetcli'`.
  - Where: `delete_nvmeof_target` and `create_nvmeof_target` methods.
  - File: `cinder/volume/targets/nvmet.py`.

HGST driver:
  - Lock scope: Process.
  - Critical section: Create volume operation.
  - Lock name: `'hgst'devices'`.
  - Where: `create_volume` method.
  - File: `cinder/volume/drivers/hgst.py`.

Solidfire driver:
  - Lock scope: Process
  - Critical section: Creating volume from an image, cloning volume, creating
    volume from a snapshot.
  - Lock name: `solidfire-{resource_id}`.
  - Where: `locked_image_id_operation` and `locked_source_id_operation`
    decorators.
  - File: `cinder/volume/drivers/solidfire.py`.

Infinidat driver:
  - Lock scope: Global.
  - Critical section: Initialize and terminate connections operations.
  - Lock name: `infinidat-{management_address}-lock`.
  - Where: `initialize_connection` and `terminate_connection` methods.
  - File: `cinder/volume/drivers/infinidat.py`.

Kaminario FC driver:
  - Lock scope: Global.
  - Critical section: Initialize and terminate connections operations.
  - Lock name: `kaminario-{san_ip}`.
  - Where: `initialize_connection` and `terminate_connection` methods.
  - File: `cinder/volume/drivers/kaminario/kaminario_fc.py`

Kaminario iSCSI driver:
  - Lock scope: Global.
  - Critical section: Initialize and terminate connections operations.
  - Lock name: `kaminario-{san_ip}`.
  - Where: `initialize_connection` and `terminate_connection` methods.
  - File: `cinder/volume/drivers/kaminario/kaminario_iscsi.py`

Dell EMC Unity:
  - Lock scope: Global.
  - Critical section: Create or get a host on the backend.
  - Lock name: `{self.host}-{name}`
  - Where: `create_host` method.
  - File: `cinder/volume/drivers/dell_emc/unity/client.py`

Dell EMC Unity:
  - Lock scope: Global.
  - Critical section: Create host and attach.
  - Lock name: `{client.host}-{host_name}`
  - Where: `_create_host_and_attach` method.
  - File: `cinder/volume/drivers/dell_emc/unity/adapter.py`

Dell EMC Unity:
  - Lock scope: Global.
  - Critical section: Create host and attach as part of the
    `initialize_connection` process, and also detach and delete host as part of
    the `terminate_connection` process.
  - Lock name: `{client.host}-{host_name}`
  - Where: `_create_host_and_attach` and `_detach_and_delete_host` methods.
  - File: `cinder/volume/drivers/dell_emc/unity/adapter.py`

Dothill:
  - Lock scope: Global
  - Critical section: Retrieving a session key from the array.  Perform HTTP
    requests on the device.
  - Lock name: `{driver_name}-{array_name}`
  - Where: `_get_session_key` and `_api_request` methods.
  - File: `cinder/volume/drivers/dothill/dothill_client.py`.

Dothill:
  - Lock scope: Global
  - Critical section: Mapping a volume as part of the `initialize_connection`
    process.
  - Lock name: `{driver_name}-{array_name}-map`
  - Where: `map_volume` method.
  - File: `cinder/volume/drivers/dothill/dothill_client.py`.


Other files
-----------

Other files that also make use of the locking mechanisms, and can be useful as
reference, are:

- `cinder/volume/drivers/dell_emc/vmax/common.py`
- `cinder/volume/drivers/dell_emc/vmax/masking.py`
- `cinder/volume/drivers/dell_emc/vmax/provision.py`
- `cinder/volume/drivers/dell_emc/vmax/rest.py`
- `cinder/volume/drivers/dell_emc/vmax/utils.py`
- `cinder/volume/drivers/fujitsu/eternus_dx_common.py`
- `cinder/volume/drivers/hpe/hpe_3par_common.py`
- `cinder/volume/drivers/hpe/hpe_lefthand_iscsi.py`
- `cinder/volume/drivers/huawei/huawei_driver.py`
- `cinder/volume/drivers/huawei/rest_client.py`
- `cinder/volume/drivers/huawei/smartx.py`
- `cinder/volume/drivers/ibm/flashsystem_common.py`
- `cinder/volume/drivers/ibm/flashsystem_fc.py`
- `cinder/volume/drivers/ibm/flashsystem_iscsi.py`
- `cinder/volume/drivers/ibm/ibm_storage/ds8k_helper.py`
- `cinder/volume/drivers/ibm/ibm_storage/ds8k_proxy.py`
- `cinder/volume/drivers/ibm/ibm_storage/ds8k_replication.py`
- `cinder/volume/drivers/ibm/ibm_storage/xiv_proxy.py`
- `cinder/volume/drivers/ibm/storwize_svc/storwize_const.py`
- `cinder/volume/drivers/ibm/storwize_svc/storwize_svc_fc.py`
- `cinder/volume/drivers/ibm/storwize_svc/storwize_svc_iscsi.py`
- `cinder/volume/drivers/inspur/instorage/instorage_const.py`
- `cinder/volume/drivers/inspur/instorage/instorage_fc.py`
- `cinder/volume/drivers/inspur/instorage/instorage_iscsi.py`
- `cinder/volume/drivers/nec/cli.py`
- `cinder/volume/drivers/nec/volume_helper.py`
- `cinder/volume/drivers/netapp/dataontap/nfs_base.py`
