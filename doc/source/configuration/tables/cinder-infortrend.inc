.. _cinder-infortrend:

.. list-table:: Description of Infortrend volume driver configuration options
   :header-rows: 1
   :class: config-ref-table

   * - Configuration option = Default value
     - Description
   * - **[DEFAULT]**
     -
   * - ``infortrend_cli_max_retries`` = ``5``
     - (Integer) The maximum retry times if a command fails.
   * - ``infortrend_cli_path`` = ``/opt/bin/Infortrend/raidcmd_ESDS10.jar``
     - (String) The Infortrend CLI absolute path.
   * - ``infortrend_cli_timeout`` = ``60``
     - (Integer) The timeout for CLI in seconds.
   * - ``infortrend_cli_cache`` = ``False``
     - (Boolean) The Infortrend CLI cache. Make sure the array is only managed by Openstack, and it is only used by one cinder-volume node. Otherwise, never enable it! The data might be asynchronous if there were any other operations.
   * - ``infortrend_pools_name`` = ``None``
     - (String) The Infortrend logical volumes name list. It is separated with comma.
   * - ``infortrend_iqn_prefix`` = ``iqn.2002-10.com.infortrend``
     - (String) Infortrend iqn prefix for iSCSI.
   * - ``infortrend_slots_a_channels_id`` = ``None``
     - (String) Infortrend raid channel ID list on Slot A for OpenStack usage. It is separated with comma.
   * - ``infortrend_slots_b_channels_id`` = ``None``
     - (String) Infortrend raid channel ID list on Slot A for OpenStack usage. It is separated with comma.
   * - ``java_path`` = ``/usr/bin/java``
     - (String) The Java absolute path.
