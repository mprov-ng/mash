#!/usr/bin/python3

import signal
from app import MprovShell

# an exit handler if we need it.
def exitHandler(signum, frame):
  pass

# setup an exit handler.
signal.signal(signal.SIGINT, exitHandler)
signal.signal(signal.SIGTERM, exitHandler)


def main():
  MprovShell().cmdloop()

def __main__():
  main()

if __name__ == "__main__":
    main()