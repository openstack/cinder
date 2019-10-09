.. _cinder-osbrick:

.. list-table:: Description of os-brick configuration options
   :header-rows: 1
   :class: config-ref-table

   * - Configuration option = Default value
     - Description
   * - **[privsep_osbrick]**
     -
   * - ``capabilities`` = ``[]``
     - (Unknown) List of Linux capabilities retained by the privsep daemon.
   * - ``group`` = ``None``
     - (String) Group that the privsep daemon should run as.
   * - ``helper_command`` = ``None``
     - (String) Command to invoke to start the privsep daemon if not using the "fork" method. If not specified, a default is generated using "sudo privsep-helper" and arguments designed to recreate the current configuration. This command must accept suitable --privsep_context and --privsep_sock_path arguments.
   * - ``user`` = ``None``
     - (String) User that the privsep daemon should run as.
