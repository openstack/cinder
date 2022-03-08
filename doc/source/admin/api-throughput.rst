=============================================
Increase Block Storage API service throughput
=============================================

By default, the Block Storage API service runs in one process. This
limits the number of API requests that the Block Storage service can
process at any given time. In a production environment, you should
increase the Block Storage API throughput by allowing the Block Storage
API service to run in as many processes as the machine capacity allows.

.. note::

   The Block Storage API service is named ``openstack-cinder-api`` on
   the following distributions: CentOS, Fedora, openSUSE, Red Hat
   Enterprise Linux, and SUSE Linux Enterprise. In Ubuntu and Debian
   distributions, the Block Storage API service is named ``cinder-api``.

To do so, use the Block Storage API service option ``osapi_volume_workers``.
This option allows you to specify the number of API service workers
(or OS processes) to launch for the Block Storage API service.

To configure this option, open the ``/etc/cinder/cinder.conf``
configuration file and set the ``osapi_volume_workers`` configuration
key to the number of CPU cores/threads on a machine.

On distributions that include ``openstack-config``, you can configure
this by running the following command instead:

.. code-block:: console

   # openstack-config --set /etc/cinder/cinder.conf \
     DEFAULT osapi_volume_workers CORES

Replace ``CORES`` with the number of CPU cores/threads on a machine.
