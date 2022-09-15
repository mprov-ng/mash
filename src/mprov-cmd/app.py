import cmd, sys

class MprovShell(cmd.Cmd):
  intro = "Welcome to the mProv shell.  Type help or ? to list commands.\n"
  prompt = '<mProv> # '
  file = None
  def do_connect(self,arg):
    'Connect to an mProv Control Center. Args: <mPCC URL> <( api <api-key> ) | ( user <username> pass <password> )> '
    pass

  def do_create(self,arg):
    'Issue a create command to the mPCC. Args create <model> <model args>'
    pass

  def do_retrieve(self,arg):
    'Issue a retrieve command to the mPCC. Args retrieve <model> <model args>'
    pass

  def do_update(self,arg):
    'Issue a update command to the mPCC. Args update <model> <model args>'
    pass

  def do_delete(self,arg):
    'Issue a delete command to the mPCC. Args delete <model> <model args>'
    pass

  def do_exit(self, arg):
    'Quit the Shell.'
    sys.exit(0)
  def do_quit(self, arg):
    'Quit the Shell.'
    sys.exit(0)
    
  # alias the http methods to their CRUD equivs.
  def do_post(self, arg):
    'Alias to create. (See \'help create\')'
    return self.do_create(arg)

  def do_get(self, arg):
    'Alias to retrieve. (See \'help retrieve\')'
    return self.do_retrieve(arg)

  def do_patch(self,arg):
    'Alias to update. (See \'help update\')'
    return self.do_update(arg)

  # pre-process commandline if needed
  def precmd(self, line):
    return line







  