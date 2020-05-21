===========================
Newton Series Release Notes
===========================

.. _Newton Series Release Notes_9.1.2_stable_newton:

9.1.2
=====

.. _Newton Series Release Notes_9.1.2_stable_newton_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1634203-netapp-cdot-fix-clone-from-nfs-image-cache-2218fb402783bc20.yaml @ b'f6a4f9346922f1eb91698114b57404f77dc0aae7'

- Fixed an issue where the NetApp cDOT NFS driver failed to clone new volumes from the image cache.


.. _Newton Series Release Notes_9.1.1_stable_newton:

9.1.1
=====

.. _Newton Series Release Notes_9.1.1_stable_newton_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/kaminario-cinder-driver-bug-1646692-7aad3b7496689aa7.yaml @ b'cedd23f421d95a67da1fca35127bb02d6ca0a82f'

- Fixed Non-WAN port filter issue in Kaminario iSCSI driver

.. releasenotes/notes/kaminario-cinder-driver-bug-1646766-fe810f5801d24f2f.yaml @ b'fbe75b62eda6b4f8012253fe3dc128de8b4855d5'

- Fixed issue of managing a VG with more than one volume in Kaminario FC and iSCSI Cinder drivers.


.. _Newton Series Release Notes_9.1.0_stable_newton:

9.1.0
=====

.. _Newton Series Release Notes_9.1.0_stable_newton_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1622057-netapp-cdot-fix-replication-status-cheesecake-volumes-804dc8b0b1380e6b.yaml @ b'0bed2f471ebba59445c82c08e63794167d0b3ecf'

- The NetApp cDOT driver now sets the ``replication_status`` attribute appropriately on volumes created within replicated backends when using host level replication.


.. _Newton Series Release Notes_9.0.0_stable_newton:

9.0.0
=====

.. _Newton Series Release Notes_9.0.0_stable_newton_Prelude:

Prelude
-------

.. releasenotes/notes/cluster_job_distribution-f916dd2e4cce6c1b.yaml @ b'8b713e5327d8b3328ae8695202098d5b61e88e7b'

Everything in Cinder's release notes related to the High Availability Active-Active effort -preluded with "HA A-A:"- is work in progress and should not be used in production until it has been completed and the appropriate release note has been issued stating its readiness for production.


.. releasenotes/notes/use-castellan-key-manager-4911c3c4908ca633.yaml @ b'682e49df2a3db3eacff3be23a2b79811d081d620'

The default key manager interface in Cinder was deprecated and the Castellan key manager interface library is now used instead. For more information about Castellan, please see http://docs.openstack.org/developer/castellan/ .


.. _Newton Series Release Notes_9.0.0_stable_newton_New Features:

New Features
------------

.. releasenotes/notes/Dell-SC-ServerOS-Config-Option-bd0e018319758e03.yaml @ b'38549395f8f4a2bd2eca1a8691a4d3c30362e354'

- dell_server_os option added to the Dell SC driver. This option allows the selection of the server type used when creating a server on the Dell DSM during initialize connection. This is only used if the server does not exist. Valid values are from the Dell DSM create server list.

.. releasenotes/notes/Dell-SC-live-volume-41bacddee199ce83.yaml @ b'fecbf75edcfcf76915221c38d46549e030c63e0f'

- Added support for the use of live volume in place of standard replication in the Dell SC driver.

.. releasenotes/notes/Dell-SC-replication-failover_host-failback-a9e9cbbd6a1be6c3.yaml @ b'6cfe6e29d7a62ac5d335401bff8a1cf40c43e0d5'

- Added replication failback support for the Dell SC driver.

.. releasenotes/notes/ZadaraStorage-13a5fff6f4fa1710.yaml @ b'a85522cc3fad56540ceea45417df07945e4f2b0f'

- Added volume driver for Zadara Storage VPSA.

.. releasenotes/notes/add-stochastic-scheduling-option-99e10eae023fbcca.yaml @ b'de66e8f8114e06d180fe3a26f62f1dfc0258da85'

- Added a new config option `scheduler_weight_handler`. This is a global option which specifies how the scheduler should choose from a listed of weighted pools. By default the existing weigher is used which always chooses the highest weight.

.. releasenotes/notes/add-stochastic-scheduling-option-99e10eae023fbcca.yaml @ b'de66e8f8114e06d180fe3a26f62f1dfc0258da85'

- Added a new weight handler `StochasticHostWeightHandler`. This weight handler chooses pools randomly, where the random probabilities are proportional to the weights, so higher weighted pools are chosen more frequently, but not all the time. This weight handler spreads new shares across available pools more fairly.

.. releasenotes/notes/allow-remove-name-and-description-for-consisgroup-408257a0a18bd530.yaml @ b'e22c24410631824e417bb35da370f10b08025e2c'

- Allow API user to remove the consistency group name or description information.

.. releasenotes/notes/backup-snapshot-6e7447db930c31f6.yaml @ b'a49711f6dd26a360047fc4d22508eb68744600ac'

- Support for snapshot backup using the optimal path in Huawei driver.

.. releasenotes/notes/backup-update-d0b0db6a7b1c2a5b.yaml @ b'c5ebe48b8ef5bebd0a1eaba3fd76993bfabc41a1'

- Added REST API to update backup name and description.

.. releasenotes/notes/bdd-pools-stats-afb4398daa9248de.yaml @ b'948ac4ab45208b37d2aa7a06b0b36ba10da54547'

- Report pools in volume stats for Block Device Driver.

.. releasenotes/notes/bp-datera-cinder-driver-update-2.1-5c6455b45563adc5.yaml @ b'c06e552fd5a16f3682bac4455f2f75c952cf4eba'

- Updating the Datera Elastic DataFabric Storage Driver to version 2.1.  This adds ACL support, Multipath support and basic IP pool support.

.. releasenotes/notes/bp-datera-cinder-driver-update-2.1-5c6455b45563adc5.yaml @ b'c06e552fd5a16f3682bac4455f2f75c952cf4eba'

- Changes config option default for datera_num_replicas from 1 to 3

.. releasenotes/notes/brcd_lookupservice_http_support-f6485b38a1feaa15.yaml @ b'b550cec9cd54b06a1945794ef60dde6215b2f4a3'

- Support for use of 'fc_southbound_protocol' configuration setting in the Brocade FC SAN lookup service.

.. releasenotes/notes/bug-1518213-a5bf2ea0d008f329.yaml @ b'c2ac7d6604bf5ff7c7b7802979e1d9b177390af5'

- Added Keystone v3 support for Swift backup driver in single user mode.

.. releasenotes/notes/cinder-coprhd-driver-11ebd149ea8610fd.yaml @ b'a7c715b4d08d369ad1246e23b54c36cf89d44a78'

- Added volume backend drivers for CoprHD FC, iSCSI and Scaleio.

.. releasenotes/notes/cluster_job_distribution-f916dd2e4cce6c1b.yaml @ b'8b713e5327d8b3328ae8695202098d5b61e88e7b'

- HA A-A: Add cluster configuration option to allow grouping hosts that share the same backend configurations and should work in Active-Active fashion.

.. releasenotes/notes/cluster_job_distribution-f916dd2e4cce6c1b.yaml @ b'8b713e5327d8b3328ae8695202098d5b61e88e7b'

- HA A-A: Updated manage command to display cluster information on service listings.

.. releasenotes/notes/cluster_job_distribution-f916dd2e4cce6c1b.yaml @ b'8b713e5327d8b3328ae8695202098d5b61e88e7b'

- HA A-A: Added cluster subcommand in manage command to list, remove, and rename clusters.

.. releasenotes/notes/cluster_job_distribution-f916dd2e4cce6c1b.yaml @ b'8b713e5327d8b3328ae8695202098d5b61e88e7b'

- HA A-A: Added clusters API endpoints for cluster related operations (index, detail, show, enable/disable).  Index and detail accept filtering by `name`, `binary`, `disabled`, `num_hosts`, `num_down_hosts`, and up/down status (`is_up`) as URL parameters.  Also added their respective policies.

.. releasenotes/notes/create-update-rules-b46cf9c07c5a3966.yaml @ b'9771c2cd4e32979358f8647e57b4bab355221c0d'

- Separate create and update rules for volume metadata.

.. releasenotes/notes/datera-2.2-driver-update-28b97aa2aaf333b6.yaml @ b'a49711f6dd26a360047fc4d22508eb68744600ac'

- Capabilites List for Datera Volume Drivers

.. releasenotes/notes/datera-2.2-driver-update-28b97aa2aaf333b6.yaml @ b'a49711f6dd26a360047fc4d22508eb68744600ac'

- Extended Volume-Type Support for Datera Volume Drivers

.. releasenotes/notes/datera-2.2-driver-update-28b97aa2aaf333b6.yaml @ b'a49711f6dd26a360047fc4d22508eb68744600ac'

- Naming convention change for Datera Volume Drivers

.. releasenotes/notes/datera-2.2-driver-update-28b97aa2aaf333b6.yaml @ b'a49711f6dd26a360047fc4d22508eb68744600ac'

- Volume Manage/Unmanage support for Datera Volume Drivers

.. releasenotes/notes/datera-2.2-driver-update-28b97aa2aaf333b6.yaml @ b'a49711f6dd26a360047fc4d22508eb68744600ac'

- New BoolOpt ``datera_debug_override_num_replicas`` for Datera Volume Drivers

.. releasenotes/notes/delete-volume-metadata-keys-3e19694401e13d00.yaml @ b'6bf2d1b94cc775850347d913cbfd3abc674f2b3d'

- Added using etags in API calls to avoid the lost update problem during deleting volume metadata.

.. releasenotes/notes/drbd-resource-options-88599c0a8fc5b8a3.yaml @ b'f1b991913603cf9f3f157328a2725b3f61b33c97'

- Configuration options for the DRBD driver that will be applied to DRBD resources; the default values should be okay for most installations.

.. releasenotes/notes/eqlx-volume-manage-unmanage-a24ec7f0d9989df3.yaml @ b'62b0acb5035beab5651e97eb29515a6dc129e064'

- Added manage/unmanage volume support for Dell Equallogic driver.

.. releasenotes/notes/falconstor-cinder-driver-dcb61441cd7601c5.yaml @ b'a6f48a55eb362b8236d9b11cbd961f28aa6fe1ba'

- Added backend driver for FalconStor FreeStor.

.. releasenotes/notes/fusionstorage-cinder-driver-8f3bca98f6e2065a.yaml @ b'ecfb70cfebed4a40c24bcb874c18eede62a4b378'

- Added backend driver for Huawei FusionStorage.

.. releasenotes/notes/generic-volume-groups-69f998ce44f42737.yaml @ b'8c74c74695043eb7a468028edb049a1611b87e77'

- Introduced generic volume groups and added create/ delete/update/list/show APIs for groups.

.. releasenotes/notes/group-snapshots-36264409bbb8850c.yaml @ b'708b9be9c0f7ee291461580a0fce92bebbc79d51'

- Added create/delete APIs for group snapshots and an API to create group from source.

.. releasenotes/notes/group-type-group-specs-531e33ee0ae9f822.yaml @ b'8cf9786e00e47421bf96fbc76f0b9b4ec8605540'

- Added group type and group specs APIs.

.. releasenotes/notes/hnas-manage-unmanage-snapshot-support-40c8888cc594a7be.yaml @ b'70bfb78875de0bdda92ea2a482c3c1009bf33833'

- Added manage/unmanage snapshot support to the HNAS NFS driver.

.. releasenotes/notes/huawei-pool-disktype-support-7c1f64639b42a48a.yaml @ b'3767c6bf743c1f287bec9114949e4c4ed7c0dc96'

- Add support for reporting pool disk type in Huawei driver.

.. releasenotes/notes/hybrid-aggregates-in-netapp-cdot-drivers-f6afa9884cac4e86.yaml @ b'7cc95f80549a45a245f988bcde9cc3ca013b8023'

- Add support for hybrid aggregates to the NetApp cDOT drivers.

.. releasenotes/notes/ibm-flashsystem-manage-unmanage-88e56837102f838c.yaml @ b'5242d1f09f2b50b9ced65b72f7aa157ed73a53d8'

- Volume manage/unmanage support for IBM FlashSystem FC and iSCSI drivers.

.. releasenotes/notes/improvement-to-query-consistency-group-detail-84a906d45383e067.yaml @ b'3eafcf5720efb3c49a374c9108f935e044f9a01e'

- Added support for querying volumes filtered by group_id using 'group_id' optional URL parameter. For example, "volumes/detail?group_id={consistency_group_id}".

.. releasenotes/notes/kaminario-fc-cinder-driver-8266641036281a44.yaml @ b'a49711f6dd26a360047fc4d22508eb68744600ac'

- New FC Cinder volume driver for Kaminario K2 all-flash arrays.

.. releasenotes/notes/kaminario-iscsi-cinder-driver-c34fadf63cd253de.yaml @ b'a49711f6dd26a360047fc4d22508eb68744600ac'

- New iSCSI Cinder volume driver for Kaminario K2 all-flash arrays.

.. releasenotes/notes/list-manageable-86c77fc39c5b2cc9.yaml @ b'1574ccf2d22cc86b83f828eadb5778a631fa9789'

- Added the ability to list manageable volumes and snapshots via GET operation on the /v2/<project_id>/os-volume-manage and /v2/<project_id>/os-snapshot-manage URLs, respectively.

.. releasenotes/notes/manage-resources-v3-c06096f75927fd3b.yaml @ b'0b0000f8fcc5dca4b2f9153b8af66da2538368fb'

- The v2 API extensions os-volume-manage and os-snapshot-manage have been mapped to the v3 resources manageable_volumes and manageable_snapshots

.. releasenotes/notes/netapp-cDOT-whole-backend-replication-support-59d7537fe3d0eb05.yaml @ b'294ee65bd3850f2b1a8c1ef10c0bd64782ed7afe'

- Added host-level (whole back end replication - v2.1) replication support to the NetApp cDOT drivers (iSCSI, FC, NFS).

.. releasenotes/notes/netapp-nfs-consistency-group-support-83eccc2da91ee19b.yaml @ b'389188c5ea9c048af927297dea08a8c9cc9506f6'

- Added Cinder consistency group for the NetApp NFS driver.

.. releasenotes/notes/nexentaedge-iscsi-ee5d6c05d65f97af.yaml @ b'672120b372b98229e27616ee35e7413ad20742c4'

- Added HA support for NexentaEdge iSCSI driver

.. releasenotes/notes/nexentaedge-nbd-eb48268723141f12.yaml @ b'ca9e590f8204032b55609d6304be95a5c35cd23d'

- Added NBD driver for NexentaEdge.

.. releasenotes/notes/nimble-add-force-backup-539e1e5c72f84e61.yaml @ b'a49711f6dd26a360047fc4d22508eb68744600ac'

- Support for force backup of in-use Cinder volumes in Nimble driver.

.. releasenotes/notes/pure-list-mangeable-fed4a1b23212f545.yaml @ b'73d2b55352e5924fe4fa93548b549c00f63ad12e'

- Add get_manageable_volumes and get_manageable_snapshots implementations for Pure Storage Volume Drivers.

.. releasenotes/notes/rename_xiv_ds8k_to_ibm_storage-154eca69c44b3f95.yaml @ b'66bcfb29b458db517a5ac11f359b53af27ac2587'

- The xiv_ds8k driver now supports IBM XIV, Spectrum Accelerate, FlashSystem A9000, FlashSystem A9000R and DS8000 storage systems, and was renamed to IBM Storage Driver for OpenStack. The changes include text changes, file names, names of cinder.conf flags, and names of the proxy classes.

.. releasenotes/notes/retype-encrypted-volume-49b66d3e8e65f9a5.yaml @ b'a49711f6dd26a360047fc4d22508eb68744600ac'

- Support for retype volumes with different encryptions including changes from unencrypted types to encrypted types and vice-versa.

.. releasenotes/notes/scaleio-manage-existing-snapshot-5bbd1818654c0776.yaml @ b'1861ed5836eb9475fe4d5cd41203b670c4e71626'

- Added support for manage/unmanage snapshot in the ScaleIO driver.

.. releasenotes/notes/scaleio-scaling-qos-50c58e43d4b54247.yaml @ b'17d7712fd1de382da24a01e2e3e7ef8e24a84895'

- Added support for scaling QoS in the ScaleIO driver. The new QoS keys are maxIOPSperGB and maxBWSperGB.

.. releasenotes/notes/scaleio-thin-provisioning-support-9c3b9203567771dd.yaml @ b'49093ae469d21499c76988b6aeaaa00cde92c069'

- Added support for oversubscription in thin provisioning in the ScaleIO driver. Volumes should have extra_specs with the key provisioning:type with value equals to either 'thick' or 'thin'. max_oversubscription_ratio can be defined by the global config or for ScaleIO specific with the config option sio_max_over_subscription_ratio. The maximum oversubscription ratio supported at the moment is 10.0.

.. releasenotes/notes/solidfire-v2.1-replication-570a1f12f70e67b4.yaml @ b'3f5e040e731f5b04382c267c3936c7f364422ee9'

- Added v2.1 replication support to SolidFire driver.

.. releasenotes/notes/support-huawei-consistency-group-b666f8f6c6cddd8f.yaml @ b'd32d9966b6cf9a3cdd7889161b566d52d435f40a'

- Added consistency group support to the Huawei driver.

.. releasenotes/notes/support-volume-glance-metadata-query-866b9e3beda2cd55.yaml @ b'fca31fc95e00580249b19ec52a2e82e7d8dcff38'

- Added support for querying volumes filtered by glance metadata key/value using 'glance_metadata' optional URL parameter. For example, "volumes/detail?glance_metadata={"image_name":"xxx"}".

.. releasenotes/notes/supported-drivers-9c95dd2378cd308d.yaml @ b'a227bf440ef47ca4c283990b0b8f35d67182e315'

- Added supported driver checks on all drivers.

.. releasenotes/notes/synology-volume-driver-c5e0f655b04390ce.yaml @ b'78d124dee28e83a4718a455c456605b8127eab09'

- Added backend driver for Synology iSCSI-supported storage.

.. releasenotes/notes/vhd-disk-format-upload-to-image-5851f9d35f4ee447.yaml @ b'e815f56bd54548e98c45e19a95f80ffd51cc21f1'

- Added support for vhd and vhdx disk-formats for volume upload-to-image.

.. releasenotes/notes/vmax-iscsi-multipath-76cc09bacf4fdfbf.yaml @ b'a49711f6dd26a360047fc4d22508eb68744600ac'

- Support for iSCSI multipathing in EMC VMAX driver.

.. releasenotes/notes/vmax-oversubscription-d61d0e3b1df2487a.yaml @ b'5377ed581083d51acfdf35faf185f0ff1ab0e86f'

- Added oversubscription support in the VMAX driver

.. releasenotes/notes/vmax-qos-eb40ed35bd2f457d.yaml @ b'a49711f6dd26a360047fc4d22508eb68744600ac'

- QoS support in EMC VMAX iSCSI and FC drivers.

.. releasenotes/notes/vmem-7000-iscsi-3c8683dcc1f0b9b4.yaml @ b'7720fce5098fa25eec55dfde6a4eec46fbe4b030'

- Added backend driver for Violin Memory 7000 iscsi storage.

.. releasenotes/notes/vnx-new-driver-7e96934c2d3a6edc.yaml @ b'a49711f6dd26a360047fc4d22508eb68744600ac'

- New Cinder driver based on storops library (available in pypi) for EMC VNX.

.. releasenotes/notes/volumes-summary-6b2485f339c88a91.yaml @ b'3db21d003fb6a2ea42043c4e262e8334541d7544'

- A new API to display the volumes summary. This summary API displays the total number of volumes and total volume's size in GB.

.. releasenotes/notes/xtremio-manage-snapshot-5737d3ad37df81d1.yaml @ b'7f44844cc103ac61940cebd89f7835c971ee0ffc'

- Added snapshot manage/unmanage support to the EMC XtremIO driver.

.. releasenotes/notes/zte_cinder_driver-76ba6d034e1b6f65.yaml @ b'6bf2d1b94cc775850347d913cbfd3abc674f2b3d'

- Added backend driver for ZTE iSCSI storage.


.. _Newton Series Release Notes_9.0.0_stable_newton_Known Issues:

Known Issues
------------

.. releasenotes/notes/os-brick-lock-dir-35bdd8ec0c0ef46d.yaml @ b'37b7a2097a5a8ba1223ba180fcf30f86b188b20e'

- When running Nova Compute and Cinder Volume or Backup services on the same host they must use a shared lock directory to avoid rare race conditions that can cause volume operation failures (primarily attach/detach of volumes). This is done by setting the "lock_path" to the same directory in the "oslo_concurrency" section of nova.conf and cinder.conf. This issue affects all previous releases utilizing os-brick and shared operations on hosts between Nova Compute and Cinder data services.


.. _Newton Series Release Notes_9.0.0_stable_newton_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/add-suppress-lvm-fd-warnings-option.402bebc03b0a9f00.yaml @ b'844aa0ac3e8068e25193a680ac0c63d68682de4b'

- In certain environments (Kubernetes for example) indirect calls to the LVM
  commands result in file descriptor leak warning messages which in turn cause
  the process_execution method to raise and exception.

  To accommodate these environments, and to maintain backward compatibility
  in Newton we add a ``lvm_suppress_fd_warnings`` bool config to the LVM driver.
  Setting this to True will append the LVM env vars to include the variable
  ``LVM_SUPPRESS_FD_WARNINGS=1``.

  This is made an optional configuration because it only applies to very specific
  environments.  If we were to make this global that would require a rootwrap/privsep
  update that could break compatibility when trying to do rolling upgrades of the
  volume service.

.. releasenotes/notes/bug-1570845-efdb0206718f4ca4.yaml @ b'622627282f4e79cb6812018db464d5e23ce9ed8e'

- The 'backup_service_inithost_offload' configuration option now defaults to 'True' instead of 'False'.

.. releasenotes/notes/create-update-rules-b46cf9c07c5a3966.yaml @ b'9771c2cd4e32979358f8647e57b4bab355221c0d'

- If policy for update volume metadata is modified in a desired way it's needed to add a desired rule for create volume metadata.

.. releasenotes/notes/db-schema-from-kilo-e6e952744531caa2.yaml @ b'10bce4b764976875cb7b3eed59b5149ba1ea070f'

- The Cinder database can now only be upgraded from changes since the Kilo release. In order to upgrade from a version prior to that, you must now upgrade to at least Kilo first, then to Newton or later.

.. releasenotes/notes/deprecate-backends-in-default-b9784a2333fe22f2.yaml @ b'395288aae47f7b87cfc8b2ff009a2e2f7af2f390'

- Any Volume Drivers configured in the DEFAULT config stanza should be moved to their own stanza and enabled via the enabled_backends config option. The older style of config with DEFAULT is deprecated and will be removed in future releases.

.. releasenotes/notes/hnas-drivers-refactoring-9dbe297ffecced21.yaml @ b'6c61bdda46e825fafec5a01ccfa958bdc1d88ac3'

- HNAS drivers have new configuration paths. Users should now use ``cinder.volume.drivers.hitachi.hnas_nfs.HNASNFSDriver`` for HNAS NFS driver and ``cinder.volume.drivers.hitachi.hnas_iscsi.HNASISCSIDriver`` for HNAS iSCSI driver.

.. releasenotes/notes/hnas_deprecate_xml-16840b5a8c25d15e.yaml @ b'3f292f024e451fa29dbd123142802e71b98a4cc0'

- HNAS drivers will now read configuration from cinder.conf.

.. releasenotes/notes/huawei-iscsi-multipath-support-a056201883909287.yaml @ b'a49711f6dd26a360047fc4d22508eb68744600ac'

- Support for iSCSI multipath in Huawei driver.

.. releasenotes/notes/huawei-support-iscsi-configuration-in-replication-7ec53737b95ffa54.yaml @ b'3c362510172b11e90424a0e83337f840a26f321d'

- Support iSCSI configuration in replication in Huawei driver.

.. releasenotes/notes/mark-scality-unsupported-530370e034a6f488.yaml @ b'aded066c995d8b1a51aeb97b7d16c79024bbe639'

- The Scality driver has been marked as unsupported and is now deprecated. enable_unsupported_drivers will need to be set to True in cinder.conf to continue to use it.

.. releasenotes/notes/netapp-cDOT-whole-backend-replication-support-59d7537fe3d0eb05.yaml @ b'294ee65bd3850f2b1a8c1ef10c0bd64782ed7afe'

- While configuring NetApp cDOT back ends, new configuration options ('replication_device' and 'netapp_replication_aggregate_map') must be added in order to use the host-level failover feature.

.. releasenotes/notes/pure-custom-user-agent-dcca4cb44b69e763.yaml @ b'925ee611d54fc6780618e8f0a881359a79cfe776'

- Pure volume drivers will need 'purestorage' python module v1.6.0 or newer. Support for 1.4.x has been removed.

.. releasenotes/notes/remove-xml-api-392b41f387e60eb1.yaml @ b'c042a05ac3872494f3a0924ebb0561e1e33a2d1c'

- The XML API has been removed in Newton release. Cinder supports only JSON API request/response format now.

.. releasenotes/notes/removed-isertgtadm-7ccefab5d3e89c59.yaml @ b'0bc4bb4fbc7f5a04732c8fe19a89e0e2d329f0f5'

- The ISERTgtAdm target was deprecated in the Kilo release. It has now been removed. You should now just use LVMVolumeDriver and specify iscsi_helper for the target driver you wish to use. In order to enable iser, please set iscsi_protocol=iser with lioadm or tgtadm target helpers.

.. releasenotes/notes/removed-rpc-topic-config-options-21c2b3f0e64f884c.yaml @ b'a49711f6dd26a360047fc4d22508eb68744600ac'

- The config options ``scheduler_topic``, ``volume_topic`` and ``backup_topic`` have been removed without a deprecation period as these had never worked correctly.

.. releasenotes/notes/rename_xiv_ds8k_to_ibm_storage-154eca69c44b3f95.yaml @ b'66bcfb29b458db517a5ac11f359b53af27ac2587'

- Users of the IBM Storage Driver, previously known as the IBM XIV/DS8K driver, upgrading from Mitaka or previous releases, need to reconfigure the relevant cinder.conf entries. In most cases the change is just removal of the xiv-ds8k field prefix, but for details use the driver documentation.

.. releasenotes/notes/rpc-apis-3.0-b745f429c11d8198.yaml @ b'8a4aecb155478e9493f4d36b080ccdf6be406eba'

- Deployments doing continuous live upgrades from master branch should not upgrade into Ocata before doing an upgrade which includes all the Newton's RPC API version bump commits (scheduler, volume). If you're upgrading deployment in a release-to-release manner, then you can safely ignore this note.

.. releasenotes/notes/scaleio-default-volume-provisioning-c648118fcc8f297f.yaml @ b'8319ea4c497aa2e25ae9b8be671ac33378aa95db'

- EMC ScaleIO driver now uses the config option san_thin_provision to determine the default provisioning type.

.. releasenotes/notes/use-castellan-key-manager-4911c3c4908ca633.yaml @ b'682e49df2a3db3eacff3be23a2b79811d081d620'

- If using the key manager, the configuration details should be updated to reflect the Castellan-specific configuration options.

.. releasenotes/notes/use-oslo_middleware_sizelimit-5f171cf1c44444f8.yaml @ b'ed4bcc0be5fbea67cf0f92ec68eefd80f2933968'

- use oslo_middleware.sizelimit rather than cinder.api.middleware.sizelimit compatibility shim

.. releasenotes/notes/vmdk_default_task_poll_interval-665f032bebfca39e.yaml @ b'd1a45ba0ddb2c551454ccb931426448ea2f66b27'

- The default interval for polling vCenter tasks in the VMware VMDK driver is changed to 2s.

.. releasenotes/notes/vmware-vmdk-config-eb70892e4ccf8f3c.yaml @ b'55b442ce192e93a26d12064645aa95fd3661babb'

- The VMware VMDK driver supports a new config option 'vmware_host_port' to specify the port number to connect to vCenter server.

.. releasenotes/notes/vnx-new-driver-7e96934c2d3a6edc.yaml @ b'a49711f6dd26a360047fc4d22508eb68744600ac'

- For EMC VNX backends, please upgrade to use ``cinder.volume.drivers.emc.vnx.driver.EMCVNXDriver``. Add config option ``storage_protocol = fc`` or ``storage_protocol = iscsi`` to the driver section to enable the FC or iSCSI driver respectively.


.. _Newton Series Release Notes_9.0.0_stable_newton_Deprecation Notes:

Deprecation Notes
-----------------

.. releasenotes/notes/datera-2.2-driver-update-28b97aa2aaf333b6.yaml @ b'a49711f6dd26a360047fc4d22508eb68744600ac'

- IntOpt ``datera_num_replicas`` is changed to a volume type extra spec option-- ``DF:replica_count``

.. releasenotes/notes/datera-2.2-driver-update-28b97aa2aaf333b6.yaml @ b'a49711f6dd26a360047fc4d22508eb68744600ac'

- BoolOpt ``datera_acl_allow_all`` is changed to a volume type extra spec option-- ``DF:acl_allow_all``

.. releasenotes/notes/deprecate-backends-in-default-b9784a2333fe22f2.yaml @ b'395288aae47f7b87cfc8b2ff009a2e2f7af2f390'

- Configuring Volume Drivers in the DEFAULT config stanza is not going to be maintained and will be removed in the next release. All backends should use the enabled_backends config option with separate stanza's for each.

.. releasenotes/notes/deprecated-nas-ip-fd86a734c92f6fae.yaml @ b'a49711f6dd26a360047fc4d22508eb68744600ac'

- Deprecated the configuration option ``nas_ip``. Use option ``nas_host`` to indicate the IP address or hostname of the NAS system.

.. releasenotes/notes/hnas-drivers-refactoring-9dbe297ffecced21.yaml @ b'6c61bdda46e825fafec5a01ccfa958bdc1d88ac3'

- The old HNAS drivers configuration paths have been marked for deprecation.

.. releasenotes/notes/hnas_deprecate_xml-16840b5a8c25d15e.yaml @ b'3f292f024e451fa29dbd123142802e71b98a4cc0'

- The XML configuration file used by the HNAS drivers is now deprecated and will no longer be used in the future. Please use cinder.conf for all driver configuration.

.. releasenotes/notes/mark-scality-unsupported-530370e034a6f488.yaml @ b'aded066c995d8b1a51aeb97b7d16c79024bbe639'

- The Scality driver has been marked as unsupported and is now deprecated. enable_unsupported_drivers will need to be set to True in cinder.conf to continue to use it. If its support status does not change it will be removed in the next release.

.. releasenotes/notes/use-castellan-key-manager-4911c3c4908ca633.yaml @ b'682e49df2a3db3eacff3be23a2b79811d081d620'

- All barbican and keymgr config options in Cinder are now deprecated. All of these options are moved to the key_manager section for the Castellan library.

.. releasenotes/notes/use-oslo_middleware_sizelimit-5f171cf1c44444f8.yaml @ b'ed4bcc0be5fbea67cf0f92ec68eefd80f2933968'

- cinder.api.middleware.sizelimit was deprecated in kilo and compatability shim added to call into oslo_middleware.  Using oslo_middleware.sizelimit directly will allow us to remove the compatability shim in a future release.

.. releasenotes/notes/vmdk_vc_51-df29eeb5fc93fbb1.yaml @ b'd1a45ba0ddb2c551454ccb931426448ea2f66b27'

- VMware VMDK driver deprecated the support for vCenter version 5.1

.. releasenotes/notes/vnx-new-driver-7e96934c2d3a6edc.yaml @ b'a49711f6dd26a360047fc4d22508eb68744600ac'

- Old VNX FC (``cinder.volume.drivers.emc.emc_cli_fc.EMCCLIFCDriver``)/ iSCSI (``cinder.volume.drivers.emc.emc_cli_iscsi.EMCCLIISCSIDriver``) drivers are deprecated. Please refer to upgrade section for information about the new driver.


.. _Newton Series Release Notes_9.0.0_stable_newton_Security Issues:

Security Issues
---------------

.. releasenotes/notes/apply-limits-to-qemu-img-29f722a1bf4b91f8.yaml @ b'8547444775e406a50d9d26a0003e9ba6554b0d70'

- The qemu-img tool now has resource limits applied which prevent it from using more than 1GB of address space or more than 2 seconds of CPU time. This provides protection against denial of service attacks from maliciously crafted or corrupted disk images.


.. _Newton Series Release Notes_9.0.0_stable_newton_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/3par-create-fc-vlun-match-set-type-babcf2cbce1ce317.yaml @ b'0912153358a686721539c48a0736a321544873a1'

- 3PAR driver creates FC VLUN of match-set type instead of host sees. With match-set, the host will see the virtual volume on specified NSP (Node-Slot-Port). This change in vlun type fixes bug 1577993.

.. releasenotes/notes/add-volume-upload-image-options-3a61a31c544fa034.yaml @ b'f8ce884002817bb76c68616314dc2dc5cedb61d6'

- Added the options ``visibility`` and ``protected`` to the os-volume_upload_image REST API call.

.. releasenotes/notes/allow-admin-quota-operations-c1c2236711224023.yaml @ b'a0a04f4332a609e854f2e67e3e9e9b723197b584'

- Projects with the admin role are now allowed to operate on the quotas of all other projects.

.. releasenotes/notes/bug-1612763-report-multiattach-enabled-NetApp-backends-0fbf2cb621e4747d.yaml @ b'5568b40d0682f6c34bce3f4dd7b5b824c93f6082'

- Volumes created on NetApp cDOT and 7mode storage systems now report 'multiattach' capability. They have always supported such a capability, but not reported it to Cinder.

.. releasenotes/notes/bug-1615451-NetApp-cDOT-fix-reporting-replication-capability-dca29f39b9fa7651.yaml @ b'623990df64092fe72a6473ac89fff1ba0d3aaec7'

- NetApp cDOT block and file drivers now report replication capability at the pool level; and are hence compatible with using the ``replication_enabled`` extra-spec in volume types.

.. releasenotes/notes/del_volume_with_fc-f024b9f2d6eaca0f.yaml @ b'a2bac00c508e6bd65add9f76250de4a35ac0c267'

- Fixed StorWize/SVC error causing volume deletion to get stuck in the 'deleting' state when using FlashCopy.

.. releasenotes/notes/fix-hnas-stats-reporting-1335e582e46ff440.yaml @ b'6bf2d1b94cc775850347d913cbfd3abc674f2b3d'

- Fixed issue where the HNAS driver was not correctly reporting THIN provisioning and related stats.

.. releasenotes/notes/live_migration_v3-ae98c0d00e64c954.yaml @ b'6bf2d1b94cc775850347d913cbfd3abc674f2b3d'

- Fixed live migration on EMC VMAX3 backends.

.. releasenotes/notes/pure-fc-wwpn-case-c1d97f3fa7663acf.yaml @ b'b5214838303e56d0556a843ee40da591cd747b87'

- Fix issue with PureFCDriver where partially case sensitive comparison of connector wwpn could cause initialize_connection to fail when attempting to create duplicate Purity host.

.. releasenotes/notes/reject-volume_clear_size-settings-larger-than-1024MiB-30b38811da048948.yaml @ b'a49711f6dd26a360047fc4d22508eb68744600ac'

- Fixed 'No Space left' error by dd command when users set the config option ``volume_clear_size`` to a value larger than the size of a volume.

.. releasenotes/notes/vmdk_backup_restore-41f807b7bc8e0ae8.yaml @ b'18325aebc609a4cf2b4b7b939716c982411b31b6'

- Fixed backup and restore of volumes in VMware VMDK driver.

.. releasenotes/notes/vmdk_image_ova-d3b3a0e72221110c.yaml @ b'd1a45ba0ddb2c551454ccb931426448ea2f66b27'

- Fixed the VMware VMDK driver to create volume from image in ova container.

.. releasenotes/notes/vmware_vmdk_paravirtual-3d5eeef96dcbcfb7.yaml @ b'93490b2c9e66eaf7b68bc3bc9a25f415a5cd0b85'

- Added support for images with vmware_adaptertype set to paraVirtual in the VMDK driver.


