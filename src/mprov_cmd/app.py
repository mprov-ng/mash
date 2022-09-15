import cmd, sys
from jinja2 import Environment, BaseLoader, select_autoescape
from io import StringIO
import csv

class MprovShell(cmd.Cmd):
  intro = "Welcome to the mProv shell.  Type help or ? to list commands.\n"
  prompt = '<mProv> # '
  file = None
  variables = {}

  def setFile(self, file):
    self.file = file

  def print(self, *args):
    'Use self.print not print() to output so we can catch it internally.'
    print(*args, file=self.stdout)

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
  def do_EOF(self, arg):
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
  
  def do_let(self, arg):
    '''
Assign an variable internal to this shell session.

You can use jinja2 template strings.  They must reference an already available
internal variable.

Starting a value with a backtick (`) will cause the value to be executed
as if it was an internal command, capturing its output into the variable.


Examples: let foo=bar
          let something=Something else {{foo}}
          let another=`pvar something
          let test=`print I have {{ something }}
'''
    key,value=arg.split('=',1)
    key = key.strip()
    value = value.strip()
    value = self.renderString(value)
    #  a backtick at the beginning of a let statement means, run this internal command.
    if value[0] == '`':
      value=self.execInternal(value[1:])    

    self.variables[key]=value
  
  def do_pvar(self,arg):
    'Display the contents of a variable'

    # see if we have a comma separated list of vars to print
    csvparser = csv.reader(arg)
    for vars in csvparser:
      for varName in vars:
        if varName in self.variables:
          self.print(f"{varName}={self.variables[varName]}")
  
  def do_print(self,arg):
    'Print random text and use internal variables via jinja2 template'
    self.print(self.renderString(arg))

  def execInternal(self, arg):
    'Executes the specified command, capturing the output, and returning it as a string. '
    old_stout = self.stdout
    self.stdout = tmpstdout = StringIO()
    self.onecmd(arg)
    self.stdout = old_stout
    return tmpstdout.getvalue()

  def renderString(self, tempStr):
    'use the internal variables to render a string.'
    jinjaEnv = Environment(
      loader=BaseLoader,
      autoescape=select_autoescape()
    )
    templateStr=jinjaEnv.from_string(tempStr)
    return templateStr.render(**self.variables)

  # pre-process commandline if needed
  def precmd(self, line):
    return line

  def cmdloop(self, intro=None):
    if self.file != None:
      # we are getting a file piped in.
      # it should be an FD, not a file name.
      for line in self.file:

        line=line.strip()
        # skip comments.
        if line[0] == "#": 
          continue
        
        self.onecmd(line)
    else:
      return super().cmdloop(intro=intro)










  