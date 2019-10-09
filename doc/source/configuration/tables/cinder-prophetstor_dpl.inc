.. _cinder-prophetstor_dpl:

.. list-table:: Description of ProphetStor Fibre Channel and iSCSi drivers configuration options
   :header-rows: 1
   :class: config-ref-table

   * - Configuration option = Default value
     - Description
   * - **[DEFAULT]**
     -
   * - ``dpl_pool`` =
     - (String) DPL pool uuid in which DPL volumes are stored.
   * - ``dpl_port`` = ``8357``
     - (Port number) DPL port number.
   * - ``iscsi_port`` = ``3260``
     - (Port number) The port that the iSCSI daemon is listening on
   * - ``san_ip`` =
     - (String) IP address of SAN controller
   * - ``san_login`` = ``admin``
     - (String) Username for SAN controller
   * - ``san_password`` =
     - (String) Password for SAN controller
   * - ``san_thin_provision`` = ``True``
     - (Boolean) Use thin provisioning for SAN volumes?
