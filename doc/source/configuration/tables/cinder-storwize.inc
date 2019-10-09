.. _cinder-storwize:

.. list-table:: Description of IBM Storwise driver configuration options
   :header-rows: 1
   :class: config-ref-table

   * - Configuration option = Default value
     - Description
   * - **[DEFAULT]**
     -
   * - ``san_ip`` =
     - (String) IP address of SAN controller
   * - ``san_login`` = ``admin``
     - (String) Username for SAN controller
   * - ``san_password`` =
     - (String) Password for SAN controller
   * - ``san_private_key`` =
     - (String) Filename of private key to use for SSH authentication
   * - ``san_ssh_port`` = ``22``
     - (Port number) SSH port to use with SAN
   * - ``ssh_conn_timeout`` = ``30``
     - (Integer) SSH connection timeout in seconds
   * - ``ssh_min_pool_conn`` = ``1``
     - (Integer) Minimum ssh connections in the pool
   * - ``ssh_max_pool_conn`` = ``5``
     - (Integer) Maximum ssh connections in the pool
   * - ``storwize_san_secondary_ip`` = ``None``
     - (String) Specifies secondary management IP or hostname to be used if san_ip is invalid or becomes inaccessible.
   * - ``storwize_svc_allow_tenant_qos`` = ``False``
     - (Boolean) Allow tenants to specify QOS on create
   * - ``storwize_svc_flashcopy_rate`` = ``50``
     - (Integer) Specifies the Storwize FlashCopy copy rate to be used when creating a full volume copy. The default is rate is 50, and the valid rates are 1-100.
   * - ``storwize_svc_flashcopy_timeout`` = ``120``
     - (Integer) Maximum number of seconds to wait for FlashCopy to be prepared.
   * - ``storwize_svc_iscsi_chap_enabled`` = ``True``
     - (Boolean) Configure CHAP authentication for iSCSI connections (Default: Enabled)
   * - ``storwize_svc_multihostmap_enabled`` = ``True``
     - (Boolean) DEPRECATED: This option no longer has any affect. It is deprecated and will be removed in the next release.
   * - ``storwize_svc_multipath_enabled`` = ``False``
     - (Boolean) Connect with multipath (FC only; iSCSI multipath is controlled by Nova)
   * - ``storwize_svc_stretched_cluster_partner`` = ``None``
     - (String) If operating in stretched cluster mode, specify the name of the pool in which mirrored copies are stored.Example: "pool2"
   * - ``storwize_svc_vol_autoexpand`` = ``True``
     - (Boolean) Storage system autoexpand parameter for volumes (True/False)
   * - ``storwize_svc_vol_compression`` = ``False``
     - (Boolean) Storage system compression option for volumes
   * - ``storwize_svc_vol_easytier`` = ``True``
     - (Boolean) Enable Easy Tier for volumes
   * - ``storwize_svc_vol_grainsize`` = ``256``
     - (Integer) Storage system grain size parameter for volumes (32/64/128/256)
   * - ``storwize_svc_vol_iogrp`` = ``0``
     - (Integer) The I/O group in which to allocate volumes
   * - ``storwize_svc_vol_nofmtdisk`` = ``False``
     - (Boolean) Specifies that the volume not be formatted during creation.
   * - ``storwize_svc_vol_rsize`` = ``2``
     - (Integer) Storage system space-efficiency parameter for volumes (percentage)
   * - ``storwize_svc_vol_warning`` = ``0``
     - (Integer) Storage system threshold for volume capacity warnings (percentage)
   * - ``storwize_svc_volpool_name`` = ``volpool``
     - (List) Comma separated list of storage system storage pools for volumes.
   * - ``storwize_svc_mirror_pool`` = ``None``
     - (String) Specifies the name of the pool in which mirrored copy is stored. Example: "pool2"
   * - ``storwize_peer_pool`` = ``None``
     - (String) Specifies the name of the peer pool for hyperswap volume, the peer pool must exist on the other site.
   * - ``storwize_preferred_host_site`` = ``{}``
     - (Dictionary) Specifies the site information for host. One WWPN or multi WWPNs used in the host can be specified. For example: storwize_preferred_host_site=site1:wwpn1,site2:wwpn2&wwpn3 or storwize_preferred_host_site=site1:iqn1,site2:iqn2
   * - ``cycle_period_seconds`` = ``300``
     - (Integer) This defines an optional cycle period that applies to Global Mirror relationships with a cycling mode of multi. A Global Mirror relationship using the multi cycling_mode performs a complete cycle at most once each period. The default is 300 seconds, and the valid seconds are 60-86400.
