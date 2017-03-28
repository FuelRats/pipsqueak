import sys
import sopel.run_script

if len(sys.argv) <= 1:
    print("No configuration file specified.  Defaulting to sopel.cfg")
    # This is a terrible, terrible idea ... but despite sopel.run_script() accepting an argv parameter, it does
    # precisely nothing with it.
    sys.argv = [sys.argv[0], '-c', 'sopel.cfg']
sopel.run_script.main()
