#!/usr/bin/python3

import signal, os, sys
from stat import S_ISFIFO
from mash.app import MprovShell

# an exit handler if we need it.
def exitHandler(signum, frame):
  pass

# setup an exit handler.
signal.signal(signal.SIGINT, exitHandler)
signal.signal(signal.SIGTERM, exitHandler)


def main():
  
  shell = MprovShell()
  
  # we are getting a script piped to us.
  if S_ISFIFO(os.fstat(0).st_mode):
    shell.setFile(sys.stdin)
  else:
    if len(sys.argv) >= 2:
      if os.path.exists(sys.argv[1]):
        # we are getting a file passed to us.
        shell.setFile(open(sys.argv[1], 'r'))
        if shell.file == None:
          print(f"Error: Unable to open {sys.argv[1]}")
          sys.exit(1)
    else:
      shell.setFile(None)
  shell.cmdloop()

def __main__():
  main()

if __name__ == "__main__":
    main()