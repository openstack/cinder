=========================================
Important Notes Regarding Closed Branches
=========================================

This README applies to release notes for branches that are closed. This
includes End of Life, Unmaintained, and Extended Maintenance branches.
The list of series, and their stable status, can be found here:

https://releases.openstack.org/

Once a stable series reaches Extended Maintenance, no new official releases
will be performed for that series. For this reason, and to save a significant
amount of time in gate jobs that build release notes, EOL branch release
notes are made static. Said another way, reno is no longer used to dynamically
generate the release notes for that branch as they are not expected to change
often.

Branches in Extended Maintenance will not be released, but they can still
accept backports of bugfixes. We may want to include release notes for these
fixes, even if they will not be included in an official release. In this case,
in addition to backporting the release note, you will need to manually refresh
the static page so those new notes will show up under a development release
version in the generated output.

To regenerate the static landing pages in this case, run the following commands
from the root of the openstack/cinder repo::

  tox -e releasenotes --notest
  .tox/releasenotes/bin/reno report \
      --title "$SERIES Series Release Notes" \
      --branch "stable/$series" | \
      sed 's/^ *$//g' > "releasenotes/source/$series.rst"

In this example, ``$SERIES`` would be the title-cased series name (i.e. Rocky),
and $series would be the series name in lower case (i.e. rocky).

This should replace the static release note page. That page should then be
added to the commit and included as part of the review.
