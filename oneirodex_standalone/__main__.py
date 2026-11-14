import sys

if sys.argv[1:2] in (['export'], ['import']):
    from oneirodex_standalone.move import main
    sys.exit(main())
if sys.argv[1:2] == ['backup']:
    from oneirodex_standalone.backup import main
    sys.exit(main(sys.argv[2:]))

from oneirodex_standalone.launcher import main

sys.exit(main())
