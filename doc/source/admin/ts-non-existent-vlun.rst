=================
Non-existent VLUN
=================

Problem
~~~~~~~

This error occurs if the 3PAR host exists with the correct host name
that the OpenStack Block Storage drivers expect but the volume was
created in a different domain.

.. code-block:: console

   HTTPNotFound: Not found (HTTP 404) NON_EXISTENT_VLUN - VLUN 'osv-DqT7CE3mSrWi4gZJmHAP-Q' was not found.


Solution
~~~~~~~~

The ``hpe3par_domain`` configuration items either need to be updated to
use the domain the 3PAR host currently resides in, or the 3PAR host
needs to be moved to the domain that the volume was created in.
