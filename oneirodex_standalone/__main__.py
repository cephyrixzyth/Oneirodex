import sys

if sys.argv[1:2] in (['export'], ['import']):
    from oneirodex_standalone.move import main
    sys.exit(main())

from oneirodex_standalone.launcher import main

sys.exit(main())
