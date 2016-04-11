
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import itertools

from cinder.api import common as cinder_api_common
from cinder.api.middleware import auth as cinder_api_middleware_auth
from cinder.api.middleware import sizelimit as cinder_api_middleware_sizelimit
from cinder.api.views import versions as cinder_api_views_versions
from cinder.backup import api as cinder_backup_api
from cinder.backup import chunkeddriver as cinder_backup_chunkeddriver
from cinder.backup import driver as cinder_backup_driver
from cinder.backup.drivers import ceph as cinder_backup_drivers_ceph
from cinder.backup.drivers import glusterfs as cinder_backup_drivers_glusterfs
from cinder.backup.drivers import google as cinder_backup_drivers_google
from cinder.backup.drivers import nfs as cinder_backup_drivers_nfs
from cinder.backup.drivers import posix as cinder_backup_drivers_posix
from cinder.backup.drivers import swift as cinder_backup_drivers_swift
from cinder.backup.drivers import tsm as cinder_backup_drivers_tsm
from cinder.backup import manager as cinder_backup_manager
from cinder.cmd import all as cinder_cmd_all
from cinder.cmd import volume as cinder_cmd_volume
from cinder.common import config as cinder_common_config
import cinder.compute
from cinder.compute import nova as cinder_compute_nova
from cinder import context as cinder_context
from cinder import coordination as cinder_coordination
from cinder.db import api as cinder_db_api
from cinder.db import base as cinder_db_base
from cinder import exception as cinder_exception
from cinder.image import glance as cinder_image_glance
from cinder.image import image_utils as cinder_image_imageutils
import cinder.keymgr
from cinder.keymgr import conf_key_mgr as cinder_keymgr_confkeymgr
from cinder.keymgr import key_mgr as cinder_keymgr_keymgr
from cinder import quota as cinder_quota
from cinder.scheduler import driver as cinder_scheduler_driver
from cinder.scheduler import host_manager as cinder_scheduler_hostmanager
from cinder.scheduler import manager as cinder_scheduler_manager
from cinder.scheduler import scheduler_options as \
    cinder_scheduler_scheduleroptions
from cinder.scheduler.weights import capacity as \
    cinder_scheduler_weights_capacity
from cinder.scheduler.weights import volume_number as \
    cinder_scheduler_weights_volumenumber
from cinder import service as cinder_service
from cinder import ssh_utils as cinder_sshutils
from cinder.transfer import api as cinder_transfer_api
from cinder.volume import api as cinder_volume_api
from cinder.volume import driver as cinder_volume_driver
from cinder.volume.drivers import block_device as \
    cinder_volume_drivers_blockdevice
from cinder.volume.drivers import blockbridge as \
    cinder_volume_drivers_blockbridge
from cinder.volume.drivers.cloudbyte import options as \
    cinder_volume_drivers_cloudbyte_options
from cinder.volume.drivers import coho as cinder_volume_drivers_coho
from cinder.volume.drivers import datera as cinder_volume_drivers_datera
from cinder.volume.drivers.dell import dell_storagecenter_common as \
    cinder_volume_drivers_dell_dellstoragecentercommon
from cinder.volume.drivers.disco import disco as \
    cinder_volume_drivers_disco_disco
from cinder.volume.drivers.dothill import dothill_common as \
    cinder_volume_drivers_dothill_dothillcommon
from cinder.volume.drivers import drbdmanagedrv as \
    cinder_volume_drivers_drbdmanagedrv
from cinder.volume.drivers.emc import emc_vmax_common as \
    cinder_volume_drivers_emc_emcvmaxcommon
from cinder.volume.drivers.emc import emc_vnx_cli as \
    cinder_volume_drivers_emc_emcvnxcli
from cinder.volume.drivers.emc import scaleio as \
    cinder_volume_drivers_emc_scaleio
from cinder.volume.drivers.emc import xtremio as \
    cinder_volume_drivers_emc_xtremio
from cinder.volume.drivers import eqlx as cinder_volume_drivers_eqlx
from cinder.volume.drivers.fujitsu import eternus_dx_common as \
    cinder_volume_drivers_fujitsu_eternusdxcommon
from cinder.volume.drivers import glusterfs as cinder_volume_drivers_glusterfs
from cinder.volume.drivers import hgst as cinder_volume_drivers_hgst
from cinder.volume.drivers.hitachi import hbsd_common as \
    cinder_volume_drivers_hitachi_hbsdcommon
from cinder.volume.drivers.hitachi import hbsd_fc as \
    cinder_volume_drivers_hitachi_hbsdfc
from cinder.volume.drivers.hitachi import hbsd_horcm as \
    cinder_volume_drivers_hitachi_hbsdhorcm
from cinder.volume.drivers.hitachi import hbsd_iscsi as \
    cinder_volume_drivers_hitachi_hbsdiscsi
from cinder.volume.drivers.hitachi import hnas_iscsi as \
    cinder_volume_drivers_hitachi_hnasiscsi
from cinder.volume.drivers.hitachi import hnas_nfs as \
    cinder_volume_drivers_hitachi_hnasnfs
from cinder.volume.drivers.hpe import hpe_3par_common as \
    cinder_volume_drivers_hpe_hpe3parcommon
from cinder.volume.drivers.hpe import hpe_lefthand_iscsi as \
    cinder_volume_drivers_hpe_hpelefthandiscsi
from cinder.volume.drivers.hpe import hpe_xp_opts as \
    cinder_volume_drivers_hpe_hpexpopts
from cinder.volume.drivers.huawei import huawei_driver as \
    cinder_volume_drivers_huawei_huaweidriver
from cinder.volume.drivers.ibm import flashsystem_common as \
    cinder_volume_drivers_ibm_flashsystemcommon
from cinder.volume.drivers.ibm import flashsystem_fc as \
    cinder_volume_drivers_ibm_flashsystemfc
from cinder.volume.drivers.ibm import flashsystem_iscsi as \
    cinder_volume_drivers_ibm_flashsystemiscsi
from cinder.volume.drivers.ibm import gpfs as cinder_volume_drivers_ibm_gpfs
from cinder.volume.drivers.ibm.storwize_svc import storwize_svc_common as \
    cinder_volume_drivers_ibm_storwize_svc_storwizesvccommon
from cinder.volume.drivers.ibm.storwize_svc import storwize_svc_fc as \
    cinder_volume_drivers_ibm_storwize_svc_storwizesvcfc
from cinder.volume.drivers.ibm.storwize_svc import storwize_svc_iscsi as \
    cinder_volume_drivers_ibm_storwize_svc_storwizesvciscsi
from cinder.volume.drivers.ibm import xiv_ds8k as \
    cinder_volume_drivers_ibm_xivds8k
from cinder.volume.drivers.infortrend.eonstor_ds_cli import common_cli as \
    cinder_volume_drivers_infortrend_eonstor_ds_cli_commoncli
from cinder.volume.drivers.lenovo import lenovo_common as \
    cinder_volume_drivers_lenovo_lenovocommon
from cinder.volume.drivers import lvm as cinder_volume_drivers_lvm
from cinder.volume.drivers.netapp import options as \
    cinder_volume_drivers_netapp_options
from cinder.volume.drivers.nexenta import options as \
    cinder_volume_drivers_nexenta_options
from cinder.volume.drivers import nfs as cinder_volume_drivers_nfs
from cinder.volume.drivers import nimble as cinder_volume_drivers_nimble
from cinder.volume.drivers.prophetstor import options as \
    cinder_volume_drivers_prophetstor_options
from cinder.volume.drivers import pure as cinder_volume_drivers_pure
from cinder.volume.drivers import quobyte as cinder_volume_drivers_quobyte
from cinder.volume.drivers import rbd as cinder_volume_drivers_rbd
from cinder.volume.drivers import remotefs as cinder_volume_drivers_remotefs
from cinder.volume.drivers.san.hp import hpmsa_common as \
    cinder_volume_drivers_san_hp_hpmsacommon
from cinder.volume.drivers.san import san as cinder_volume_drivers_san_san
from cinder.volume.drivers import scality as cinder_volume_drivers_scality
from cinder.volume.drivers import sheepdog as cinder_volume_drivers_sheepdog
from cinder.volume.drivers import smbfs as cinder_volume_drivers_smbfs
from cinder.volume.drivers import solidfire as cinder_volume_drivers_solidfire
from cinder.volume.drivers import tegile as cinder_volume_drivers_tegile
from cinder.volume.drivers import tintri as cinder_volume_drivers_tintri
from cinder.volume.drivers.violin import v7000_common as \
    cinder_volume_drivers_violin_v7000common
from cinder.volume.drivers.vmware import vmdk as \
    cinder_volume_drivers_vmware_vmdk
from cinder.volume.drivers import vzstorage as cinder_volume_drivers_vzstorage
from cinder.volume.drivers.windows import windows as \
    cinder_volume_drivers_windows_windows
from cinder.volume.drivers import xio as cinder_volume_drivers_xio
from cinder.volume.drivers.zfssa import zfssaiscsi as \
    cinder_volume_drivers_zfssa_zfssaiscsi
from cinder.volume.drivers.zfssa import zfssanfs as \
    cinder_volume_drivers_zfssa_zfssanfs
from cinder.volume import manager as cinder_volume_manager
from cinder.wsgi import eventlet_server as cinder_wsgi_eventletserver
from cinder.zonemanager.drivers.brocade import brcd_fabric_opts as \
    cinder_zonemanager_drivers_brocade_brcdfabricopts
from cinder.zonemanager.drivers.brocade import brcd_fc_zone_driver as \
    cinder_zonemanager_drivers_brocade_brcdfczonedriver
from cinder.zonemanager.drivers.cisco import cisco_fabric_opts as \
    cinder_zonemanager_drivers_cisco_ciscofabricopts
from cinder.zonemanager.drivers.cisco import cisco_fc_zone_driver as \
    cinder_zonemanager_drivers_cisco_ciscofczonedriver
from cinder.zonemanager import fc_zone_manager as \
    cinder_zonemanager_fczonemanager


def list_opts():
    return [
        ('FC-ZONE-MANAGER',
            itertools.chain(
                cinder_zonemanager_fczonemanager.zone_manager_opts,
                cinder_zonemanager_drivers_brocade_brcdfczonedriver.brcd_opts,
                cinder_zonemanager_drivers_cisco_ciscofczonedriver.cisco_opts,
            )),
        ('KEYMGR',
            itertools.chain(
                cinder_keymgr_keymgr.encryption_opts,
                cinder.keymgr.keymgr_opts,
                cinder_keymgr_confkeymgr.key_mgr_opts,
            )),
        ('DEFAULT',
            itertools.chain(
                cinder_backup_driver.service_opts,
                cinder_api_common.api_common_opts,
                cinder_backup_drivers_ceph.service_opts,
                cinder_volume_drivers_smbfs.volume_opts,
                cinder_backup_chunkeddriver.chunkedbackup_service_opts,
                cinder_volume_drivers_san_san.san_opts,
                cinder_volume_drivers_hitachi_hnasnfs.NFS_OPTS,
                cinder_wsgi_eventletserver.socket_opts,
                cinder_sshutils.ssh_opts,
                cinder_volume_drivers_netapp_options.netapp_proxy_opts,
                cinder_volume_drivers_netapp_options.netapp_connection_opts,
                cinder_volume_drivers_netapp_options.netapp_transport_opts,
                cinder_volume_drivers_netapp_options.netapp_basicauth_opts,
                cinder_volume_drivers_netapp_options.netapp_cluster_opts,
                cinder_volume_drivers_netapp_options.netapp_7mode_opts,
                cinder_volume_drivers_netapp_options.netapp_provisioning_opts,
                cinder_volume_drivers_netapp_options.netapp_img_cache_opts,
                cinder_volume_drivers_netapp_options.netapp_eseries_opts,
                cinder_volume_drivers_netapp_options.netapp_nfs_extra_opts,
                cinder_volume_drivers_netapp_options.netapp_san_opts,
                cinder_volume_drivers_ibm_storwize_svc_storwizesvciscsi.
                storwize_svc_iscsi_opts,
                cinder_backup_drivers_glusterfs.glusterfsbackup_service_opts,
                cinder_backup_drivers_tsm.tsm_opts,
                cinder_volume_drivers_fujitsu_eternusdxcommon.
                FJ_ETERNUS_DX_OPT_opts,
                cinder_volume_drivers_ibm_gpfs.gpfs_opts,
                cinder_volume_drivers_violin_v7000common.violin_opts,
                cinder_volume_drivers_nexenta_options.NEXENTA_CONNECTION_OPTS,
                cinder_volume_drivers_nexenta_options.NEXENTA_ISCSI_OPTS,
                cinder_volume_drivers_nexenta_options.NEXENTA_DATASET_OPTS,
                cinder_volume_drivers_nexenta_options.NEXENTA_NFS_OPTS,
                cinder_volume_drivers_nexenta_options.NEXENTA_RRMGR_OPTS,
                cinder_volume_drivers_nexenta_options.NEXENTA_EDGE_OPTS,
                cinder_exception.exc_log_opts,
                cinder_common_config.global_opts,
                cinder_scheduler_weights_capacity.capacity_weight_opts,
                cinder_volume_drivers_sheepdog.sheepdog_opts,
                [cinder_api_middleware_sizelimit.max_request_body_size_opt],
                cinder_volume_drivers_solidfire.sf_opts,
                cinder_backup_drivers_swift.swiftbackup_service_opts,
                cinder_volume_drivers_cloudbyte_options.
                cloudbyte_add_qosgroup_opts,
                cinder_volume_drivers_cloudbyte_options.
                cloudbyte_create_volume_opts,
                cinder_volume_drivers_cloudbyte_options.
                cloudbyte_connection_opts,
                cinder_volume_drivers_cloudbyte_options.
                cloudbyte_update_volume_opts,
                cinder_service.service_opts,
                cinder.compute.compute_opts,
                cinder_volume_drivers_drbdmanagedrv.drbd_opts,
                cinder_volume_drivers_dothill_dothillcommon.common_opts,
                cinder_volume_drivers_dothill_dothillcommon.iscsi_opts,
                cinder_volume_drivers_glusterfs.volume_opts,
                cinder_volume_drivers_pure.PURE_OPTS,
                cinder_context.context_opts,
                cinder_scheduler_driver.scheduler_driver_opts,
                cinder_volume_drivers_scality.volume_opts,
                cinder_volume_drivers_emc_emcvnxcli.loc_opts,
                cinder_volume_drivers_vmware_vmdk.vmdk_opts,
                cinder_volume_drivers_lenovo_lenovocommon.common_opts,
                cinder_volume_drivers_lenovo_lenovocommon.iscsi_opts,
                cinder_backup_drivers_posix.posixbackup_service_opts,
                cinder_volume_drivers_emc_scaleio.scaleio_opts,
                [cinder_db_base.db_driver_opt],
                cinder_volume_drivers_eqlx.eqlx_opts,
                cinder_transfer_api.volume_transfer_opts,
                cinder_db_api.db_opts,
                cinder_scheduler_weights_volumenumber.
                volume_number_weight_opts,
                cinder_volume_drivers_coho.coho_opts,
                cinder_volume_drivers_xio.XIO_OPTS,
                cinder_volume_drivers_ibm_storwize_svc_storwizesvcfc.
                storwize_svc_fc_opts,
                cinder_volume_drivers_zfssa_zfssaiscsi.ZFSSA_OPTS,
                cinder_volume_driver.volume_opts,
                cinder_volume_driver.iser_opts,
                cinder_api_views_versions.versions_opts,
                cinder_volume_drivers_nimble.nimble_opts,
                cinder_volume_drivers_windows_windows.windows_opts,
                cinder_volume_drivers_san_hp_hpmsacommon.common_opts,
                cinder_volume_drivers_san_hp_hpmsacommon.iscsi_opts,
                cinder_image_glance.glance_opts,
                cinder_image_glance.glance_core_properties_opts,
                cinder_volume_drivers_hpe_hpelefthandiscsi.hpelefthand_opts,
                cinder_volume_drivers_lvm.volume_opts,
                cinder_volume_drivers_emc_emcvmaxcommon.emc_opts,
                cinder_volume_drivers_remotefs.nas_opts,
                cinder_volume_drivers_remotefs.volume_opts,
                cinder_volume_drivers_emc_xtremio.XTREMIO_OPTS,
                cinder_backup_drivers_google.gcsbackup_service_opts,
                [cinder_api_middleware_auth.use_forwarded_for_opt],
                cinder_volume_drivers_hitachi_hbsdcommon.volume_opts,
                cinder_volume_drivers_infortrend_eonstor_ds_cli_commoncli.
                infortrend_esds_opts,
                cinder_volume_drivers_infortrend_eonstor_ds_cli_commoncli.
                infortrend_esds_extra_opts,
                cinder_volume_drivers_hitachi_hnasiscsi.iSCSI_OPTS,
                cinder_volume_drivers_rbd.rbd_opts,
                cinder_volume_drivers_tintri.tintri_opts,
                cinder_backup_api.backup_api_opts,
                cinder_volume_drivers_hitachi_hbsdhorcm.volume_opts,
                cinder_backup_manager.backup_manager_opts,
                cinder_volume_drivers_ibm_storwize_svc_storwizesvccommon.
                storwize_svc_opts,
                cinder_volume_drivers_hitachi_hbsdfc.volume_opts,
                cinder_quota.quota_opts,
                cinder_volume_drivers_huawei_huaweidriver.huawei_opts,
                cinder_volume_drivers_dell_dellstoragecentercommon.
                common_opts,
                cinder_scheduler_hostmanager.host_manager_opts,
                [cinder_scheduler_manager.scheduler_driver_opt],
                cinder_backup_drivers_nfs.nfsbackup_service_opts,
                cinder_volume_drivers_blockbridge.blockbridge_opts,
                [cinder_scheduler_scheduleroptions.
                    scheduler_json_config_location_opt],
                cinder_volume_drivers_zfssa_zfssanfs.ZFSSA_OPTS,
                cinder_volume_drivers_disco_disco.disco_opts,
                cinder_volume_drivers_hgst.hgst_opts,
                cinder_image_imageutils.image_helper_opts,
                cinder_compute_nova.nova_opts,
                cinder_volume_drivers_ibm_flashsystemfc.flashsystem_fc_opts,
                cinder_volume_drivers_prophetstor_options.DPL_OPTS,
                cinder_volume_drivers_hpe_hpexpopts.FC_VOLUME_OPTS,
                cinder_volume_drivers_hpe_hpexpopts.COMMON_VOLUME_OPTS,
                cinder_volume_drivers_hpe_hpexpopts.HORCM_VOLUME_OPTS,
                cinder_volume_drivers_hitachi_hbsdiscsi.volume_opts,
                cinder_volume_manager.volume_manager_opts,
                cinder_volume_drivers_ibm_flashsystemiscsi.
                flashsystem_iscsi_opts,
                cinder_volume_drivers_tegile.tegile_opts,
                cinder_volume_drivers_ibm_flashsystemcommon.flashsystem_opts,
                [cinder_volume_api.allow_force_upload_opt],
                [cinder_volume_api.volume_host_opt],
                [cinder_volume_api.volume_same_az_opt],
                [cinder_volume_api.az_cache_time_opt],
                cinder_volume_drivers_ibm_xivds8k.xiv_ds8k_opts,
                cinder_volume_drivers_hpe_hpe3parcommon.hpe3par_opts,
                cinder_volume_drivers_datera.d_opts,
                cinder_volume_drivers_blockdevice.volume_opts,
                cinder_volume_drivers_quobyte.volume_opts,
                cinder_volume_drivers_vzstorage.vzstorage_opts,
                cinder_volume_drivers_nfs.nfs_opts,
            )),
        ('CISCO_FABRIC_EXAMPLE',
            itertools.chain(
                cinder_zonemanager_drivers_cisco_ciscofabricopts.
                cisco_zone_opts,
            )),
        ('BRCD_FABRIC_EXAMPLE',
            itertools.chain(
                cinder_zonemanager_drivers_brocade_brcdfabricopts.
                brcd_zone_opts,
            )),
        ('COORDINATION',
            itertools.chain(
                cinder_coordination.coordination_opts,
            )),
        ('BACKEND',
            itertools.chain(
                [cinder_cmd_volume.host_opt],
                [cinder_cmd_all.volume_cmd.host_opt],
            )),
    ]
