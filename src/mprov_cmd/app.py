import cmd, sys, json
from curses import raw
from jinja2 import Environment, BaseLoader, select_autoescape
from io import StringIO
import csv, base64
import requests

class MprovShell(cmd.Cmd):
  intro = "Welcome to the mProv shell.  Type help or ? to list commands.\n"
  prompt = '<mProv> # '
  file = None
  variables = {}
  session = requests.Session()
  mprovURL = ""
  models=[]

  def setFile(self, file):
    self.file = file

  def print(self, *args):
    'Use self.print not print() to output so we can catch it internally.'
    print(*args, file=self.stdout)

  def do_connect(self,arg):
    '''
Connect to an mProv Control Center.

Usage: 
    connect <mprov_url> apikey <api_key> - Connects with an API key

    connect <mprov_url> user <user> password <password> - connects with a username and password.
    
    connect - With no arguments, mprov-cmd will try to read the .mprov-cmd.yaml file in the user's 
    home directory (~/.mprov-cmd.yaml) and then try to read /etc/mprov/mprov-cmd.yaml

    '''
    args = arg.split(' ')
    authHeader = ""
    if len(args) == 0:
      # TODO: we are reading from a yaml file.
      self.print("Not Implemented")
      return
    if len(args) > 0:
      self.mprovURL = args[0]
      if 'apikey' == args[1]: 
        # we are using an API key
        authHeader = f"Api-key {args[2]}"
        
      if 'user' == args[2]:
        # We are using plain text auth
        rawAuthStr=f"{args[2]}:{args[4]}"
        encAuthStr=base64.b64encode(rawAuthStr)
        authHeader = f"Basic {encAuthStr}"
    self._connectToMPCC(authHeader)


  def do_disconnect(self, arg):
    self.session.close()

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
  def do_models(self,arg):
    'Display a list of supported data models'
    for model in self.models:
      self.print(model)

  def do_model(self, arg):
    'Display the information about a specific model'
    model = arg
    if model in self.models:
      # grab the data from the mPCC
      response = self.session.get(f"{self.mprovURL}/datamodel/?model={model}")
      if response.status_code == 200:
        self.print(response.text)
        return
      self.print(f"Error: Unable to retrieve model {model} from the mPCC.")
      return
    self.print(f"Error: Unknown model {model}")

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
  
  def _connectToMPCC(self, authHeader):

    self.session.headers.update({
      'Content-Type': 'application/json',
      'Authorization': authHeader,
    })
    try:
      response = self.session.get(self.mprovURL, stream=True)
    except:
      self.print(f"Error: Unable to communicate with mPCC {self.mprovURL}")
      return
    if response.status_code==200:
      # we connected, get the supported data models.
      self._getMPCCModels()

  def _getMPCCModels(self):
    response = self.session.get(f"{self.mprovURL}/datamodel/")
    if response.status_code == 200:
      self.models = response.json()['datamodels']
    else:
      self.print(f"Error: Unable to retrieve the data models from the mPCC, code: {response.status_code}")
    
    
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










  