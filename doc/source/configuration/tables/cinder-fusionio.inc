
Volume driver configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~

This section describes how to configure the FusionStorage Volume Driver.

To configure the volume driver, follow the steps below:

#. Configure the ``cinder.conf`` file.

   In the ``[default]`` block of ``/etc/cinder/cinder.conf``,
   enable the ``VOLUME_BACKEND``:

   .. code-block:: ini

      enabled_backends = VOLUME_BACKEND

   Add a new block ``[VOLUME_BACKEND]``, and add the following contents:

   .. code-block:: ini

    [VOLUME_BACKEND]
    volume_driver = cinder.volume.drivers.fusionstorage.dsware.DSWAREDriver
    volume_backend_name = backend_name
    manager_ips =
        host1:ip1,
        host2:ip2
    storage =
        UserName: username,
        Password: password,
        RestURL: url,
        StoragePool: pool0;pool1;pool2

   * ``volume_driver`` indicates the loaded driver.

   * ``volume_backend_name`` indicates the name of the backend.

   * ``manager_ips`` indicates the management host name and its corresponding IP address;
   The parameters takes the standard dict config form, such as
   manager_ips = host1:ip1, host2:ip2.

   * ``storage``  indicates the FusionStorage and user info, include "UserName",
   "Password", "RestURL", "StoragePool". The parameters takes the standard
   dict config form.

#. Run the :command:`service cinder-volume restart` command to restart the
   Block Storage service.

