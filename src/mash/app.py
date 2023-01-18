import cmd, sys, json
import os
from os import fork
from jinja2 import Environment, BaseLoader
from io import StringIO
import csv, base64
import requests
import shlex
import yaml
import importlib


def exception_handler(exc_type, exc_value, exc_traceback):
  print(f"There was an internal exception. {exc_value}", file=sys.stderr)

class MprovShell(cmd.Cmd):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    
  configfile = "/etc/mprov/mash.yaml"
  intro = "Welcome to the mProv shell.  Type help or ? to list commands.\n"
  prompt = '<mProv> # '
  file = None
  variables = {}
  session = requests.Session()
  mprovURL = ""
  apikey = ""
  models={}
  processes = []
  quiet = False
  config_data={}
  inForLoop = False
  forLoopCmds = []
  forLoopItemName = ""
  forLoopList = [] # the list we will iterate on


  def setFile(self, file):
    self.file = file

  def print(self, *args):
    'Use self.print not print() to output so we can catch it internally.'
    print(*args, file=self.stdout)
  
  def err(self, *args):
    print(*args, file=sys.stderr)

  def emptyline(self):
    return 

  def yaml_include(self, loader, node):
    # Placeholder: Unused.  
    return {}

  def load_config(self):
    # load the config yaml
    # print(self.configfile)
    yaml.add_constructor("!include", self.yaml_include)

    if os.path.isfile(os.path.expanduser("~/.mprov-mash.yaml")) and os.access(os.path.expanduser("~/.mprov-mash.yaml"), os.R_OK):
      self.configfile = os.path.expanduser("~/.mprov-mash.yaml")
    # print(self.configfile)
    if not(os.path.isfile(self.configfile) and os.access(self.configfile, os.R_OK)):
      return False


    with open(self.configfile, "r") as yamlfile:
      self.config_data = yaml.load(yamlfile, Loader=yaml.FullLoader)
    # flatten the config space
    result = {}
    for entry in self.config_data:
      result.update(entry)
    self.config_data = result
    return True

  def default(self,args):
    '''
    Default command to run when the command is not recognized.

    Here we will try to find a plugin with the name that matches the first part of the command,
    and pass the rest of the line to the plugin

    '''
    if " " not in args:
      pluginName = args
    else:
      pluginName, args = args.split(" ", 1)
    pluginMod = importlib.util.find_spec(f"mash.plugins.{pluginName}")
    if pluginMod is not None:
      try:
        plugin = importlib.import_module(f"mash.plugins.{pluginName}")
        pluginCmd = getattr(plugin, "PluginCMD")
        if pluginCmd is not None:
          pluginInstance = pluginCmd(self)
          if pluginInstance is None:
            self.err(f"Error: Unable to instantiate plugin {pluginName}")
            return
          # send the line off to the plugin
          pluginInstance.onecmd(args)
        else:
          self.err(f"Error: 'PluginCMD' class not found on plugin {pluginName}")
          return
      except Exception as e:
        self.err(f"Error: Exception in plugin {pluginName}. {e}")
        return
      return
      # Look in mash.plugins for mash.plugins.<first arg> for a matching plugin.
    self.err(f"Error: Unrecognized command {pluginName}")

   
    
  def do_connect(self,arg):
    '''
Connect to an mProv Control Center.

Usage: 
    connect <mprov_url> apikey <api_key> - Connects with an API key

    connect <mprov_url> user <user> password <password> - connects with a username and password.
    
    connect - With no arguments, mash will try to read the .mprov-mash.yaml file in the user's 
    home directory (~/.mprov-mash.yaml) and then try to read /etc/mprov/mprov-mash.yaml

    '''
    authHeader = ""
    if " " not in arg:
      # we are reading from a yaml file.
      if not self.load_config():
        self.err("Unable to find working config file.")
        return
      if 'apikey' in self.config_data['global']:
        if self.config_data['global']['apikey'] != "":
          authHeader = f"Api-Key {self.config_data['global']['apikey']}"  
      if 'mprovURL' in self.config_data['global']:
        if self.config_data['global']['mprovURL'] != "":
          self.mprovURL = self.config_data['global']['mprovURL']
    
    else:
      args = arg.split(' ')
          
      if len(args) > 1:
        self.mprovURL = args[0]
        if 'apikey' == args[1]: 
          # we are using an API key
          authHeader = f"Api-Key {args[2]}"
          
        if 'user' == args[2]:
          # We are using plain text auth
          rawAuthStr=f"{args[2]}:{args[4]}"
          encAuthStr=base64.b64encode(rawAuthStr)
          authHeader = f"Basic {encAuthStr}"
    self._connectToMPCC(authHeader)


  def do_disconnect(self, arg):
    if(self.processes):
      self.print("Waiting for background processes")
      while self.processes:
        pid, _ = os.wait()
        if pid != 0:
          if not self.quiet:
            print(f"PID {pid} finished.")
          self.processes.remove(pid)
    self.session.close()

  def do_create(self,arg):
    'Issue a create command to the mPCC. Args create <model> <model args>'

    self._sendHttpRequest("post", arg, True)

  def do_retrieve(self,arg):
    '''
Issue a retrieve command to the mPCC. 
  
Args:
  retrieve <model> [model_args]

Return: 
  Sets MPROV_RESULT to the python object representing the returned object, or sets
  MPROV_RESULT to None if there was an error.
'''
    self._sendHttpRequest("get", arg)
    
  def do_update(self,arg):
    'Issue a update command to the mPCC. Args update <model> <model args>'
    self._sendHttpRequest("patch",arg)
    

  def do_delete(self,arg):
    'Issue a delete command to the mPCC. Args delete <model> <model args>'
    self._sendHttpRequest("delete", arg)

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
    if value=="":
      self.print("Error: Empty value in Assignment")
      return
    #  a backtick at the beginning of a let statement means, run this internal command.
    if value[0] == '`':
      value=self.execInternal(value[1:])    
    
    # a dollar sign means copy the internal variable to 
    # a new internal variable.
    if value[0] == '$':
      intVar = value[1:]
      if intVar in self.variables:
        self.variables[key] = self.variables[intVar]
        return
      else:
        self.print(f"Error: Undefined variable ${intVar}")
        return
    
    # otherwise, assign the given value.
    self.variables[key]=value

  def do_models(self,arg):
    'Display a list of supported data models'
    for model in self.models:
      self.print(model)

  def do_model(self, arg):
    'Display the information about a specific model'
    model = arg
    if model in self.models:
      
      self.print(self.models[model])
      
      return
    self.print(f"Error: Unknown model {model}")

  def do_pvar(self,arg):
    'Display the contents of a variable, or a comma separated list of variables'

    # see if we have a comma separated list of vars to print
    if ',' not in arg:
      if arg in self.variables:
        self.print(f"{arg}={self.variables[arg]}")
      else:
        self.print(f"Error: Unknown variable {arg}")
      return
    csvparser = csv.reader(arg)
    for vars in csvparser:
      for varName in vars:
        if varName in self.variables:
          self.print(f"{varName}={self.variables[varName]}")
  def do_p(self,arg):
    'Alias to pvar'
    self.do_pvar(arg)

  def do_print(self,arg):
    'Print random text and use internal variables'
    self.print(arg)

  def do_foreach(self, arg):
    ''' 
        Run a loop of commands.  Syntax: foreach item in list
        item is a single item from a list
        list is an actual array or a white space separated string
        MUST end your loop with endforeach.
    '''

    if " " not in arg:
      self.err("Error: Syntax error")
      return
    args = shlex.split(arg, 2)
    if len(args) < 3 :
      self.err("Error: Syntax error")
      return
    if args[1] != "in":
      self.err("Error: Syntax error")
      return
    if " " in args[2]:
      # convert the string to a list
      self.forLoopList = args[2].split(" ")
    else:
      # print(args)
      if args[2] not in self.variables:
        self.err(f"Error: {args[2]} is not defined")
        return
      if type(self.variables[args[2]]) is not list:
        self.err(f"Error: {args[2]} must be type list")
        return
      # print(args[2])
      self.forLoopList = self.variables[args[2]]
    self.variables[args[0]] = None
    self.forLoopItemName = args[0]
    
    self.prompt = "<mProv> -for-> "
    self.inForLoop = True
    

  def do_endforeach(self,arg):
    ''' Ends a foreach loop, attempts to run the loop, 
        and then returns to normal operation. If any command
        in the loop fails, the loop stops and an error is set
    '''
    self.prompt = "<mProv> # "
    self.inForLoop = False
    if len(self.forLoopCmds) > 0:
      # Run our for loop cmds.
      for i in self.forLoopList:
        self.variables[self.forLoopItemName] = i
        for command in self.forLoopCmds:
          if self.onecmd(self.renderString(command)) == False:
            self.err("Error running loop.")
            self.forLoopCmds.clear()
            self.forLoopList=[]
            self.forLoopItemName = ""
            return
      self.forLoopCmds.clear()
      self.forLoopList=[]
      self.forLoopItemName = ""
            
  def do_seq(self, arg):
    '''
    Syntax: seq <var> <start> <end>
    Creates a sequence as a list and puts it in variable var
    '''
    if " " not in arg:
      self.err("Error: Invalid Syntax")
      return
    args = arg.split(" ")
    self.variables[args[0]] = []
    for i in range(int(args[1]), int(args[2]) + 1):
      self.variables[args[0]].append(i)

    
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
      autoescape=False
    )
    try:    
      templateStr=jinjaEnv.from_string(tempStr)
      return templateStr.render(**self.variables)
    except Exception as e:
      self.print(f"Error trying to template, {e.message}")
    return tempStr
  
  def _connectToMPCC(self, authHeader):
    self.session.headers.update({
      'Content-Type': 'application/json',
      'Authorization': authHeader,
      'Connection': 'close',
    })
    try:
      adapter = requests.adapters.HTTPAdapter(pool_connections=100, pool_maxsize=100, max_retries=20, pool_block=True)
      self.session.mount('https://', adapter)
      self.session.mount('http://', adapter)
      response = self.session.get(self.mprovURL, stream=True)
    except:
      self.print(f"Error: Unable to communicate with mPCC {self.mprovURL}")
      return
    if response.status_code==200:
      # we connected, get the supported data models.
      self._getMPCCModels()

  def _sendHttpRequest(self, method, arg, checkargs=False, background=False):
    if arg[-1] == '&':
      # if the last character of the string is an &, fork and return as parent.
      background = True
      ret = fork()
      if ret != 0:
        # we are parent
        # Process tracking, 
        self.processes.append(ret)
        # do nothing and return.
        return
      arg=arg[:-1]
        
    # parse the model out, and the args, if any were passed.
    try:
      model, model_args = arg.split(' ', 1)
    except:
      model = arg
      model_args = ""
      
    if model not in self.models:
      self.print(f"Error: Unknown Model {model}.")
      return
    
    # get the endpoint
    if 'endpoint' in self.models[model]:
      mEndpoint = self.models[model]['endpoint']
    else:
      self.print(f"Error: Model {model} does not seem to have a registered endpoint in the mPCC.")
      return
    requestData = {}
    idStr = ""
    queryString = ""
    if method  == "post" or method == "patch":
      
      # check our args against the data structure.
      for marg in shlex.split(model_args):
        key, value = marg.split("=", 1)
        if key in self.models[model]['fields']:
          requestData[key]=value
          if key == 'id' or key == 'pk':
            idStr=f"{value}/"
        else:
          self.print(f"Error: Model {model} does not have field {key}")
          self.print(f"Check 'model {model}' and try again.")
          self.variables['MPROV_RESULT']=None
          return
      if checkargs:
        # make sure the required fields are present
        for field in self.models[model]['fields']:
          if field not in requestData and self.models[model]['fields'][field]['required']:
            self.print(f"Error: Missing field required {field} for model {model}.")
            self.print(f"Check 'model {model}' and try again.")
            self.variables['MPROV_RESULT']=None
            return
    elif method == "get" or method == "delete":
      # build query strings
      if model_args == "" :
        queryString=""
      else:
        queryString = "?"

        for marg in model_args.split(" "):
          try:
            key, value = marg.split('=',1)
            if key == 'id' or key == 'pk':
              # we got an id, so add it to the URL
              idStr=f"{value}/"
          except:
            pass
          queryString += f"{marg}&"
    
    # TODO: add the ability to detect if we should background the request.
    
    if method == "post":
      response = self.session.post(f"{self.mprovURL}{mEndpoint}{idStr}{queryString}", data=json.dumps(requestData), headers={'Connection':'close'}, timeout=None, stream=True)
    elif method == "get":
      response = self.session.get(f"{self.mprovURL}{mEndpoint}{idStr}{queryString}", timeout=None, stream=True) # TODO: Add query string and ID stuff.
    elif method == "patch":
      response = self.session.patch(f"{self.mprovURL}{mEndpoint}{idStr}{queryString}", data=json.dumps(requestData),timeout=None, stream=True) # TODO:
    elif method == "delete":
      response = self.session.delete(f"{self.mprovURL}{mEndpoint}{idStr}{queryString}",timeout=None, stream=True) # TODO
    else: 
      response = None
      self.print(f"Error: Unsupported method {method}.")
      return
    
    if response.status_code < 200 or response.status_code > 299 :
      self.print(f"Error: Communications error with mPCC, code: {response.status_code}")
      self.print(f"{response.text}")
      return

    # only assign MPROV_RESULT if we are not running in the background/parallel.  
    if not background:
      try:
        self.variables['MPROV_RESULT'] = response.json()
      except: 
        print("Error setting MPROV_RESULT")
        # self.print(f"{response.text}")
        self.variables['MPROV_RESULT'] = None
        self.print("ERROR")
        return
      if not self.quiet:
        self.print("OK")
    else:
      # self.print(f"{response.text}")
      # exit because we were backgrounded and forked.  Don't want to return to main.
      sys.exit(0)


  def _getMPCCModels(self):
    response = self.session.get(f"{self.mprovURL}/datamodel/")
    if response.status_code == 200:
      modellist = response.json()['datamodels']
      for model in modellist:
        response = self.session.get(f"{self.mprovURL}/datamodel/?model={model}")
        if response.status_code != 200:
          self.print(f"Error: Unable to retrieve data structure for model {model}, code: {response.status_code}")
          continue
        self.models[model] = response.json()
    else:
      self.print(f"Error: Unable to retrieve the data models from the mPCC, code: {response.status_code}")
    
    
  # pre-process commandline if needed
  def precmd(self, line):
    # pass the string through the jinja2 template engine and map internal variable values.
    if self.inForLoop :
      # we are in a for loop, so just add the command to the forLoopCmds list
      if line == "endforeach":
        return line
      self.forLoopCmds.append(line)
      line = ""
    else:
      line = self.renderString(line)
    return line

  def cmdloop(self, intro=None):
    if self.file != None:
      self.quiet = True
      # we are getting a file piped in.
      # it should be an FD, not a file name.
      for line in self.file:

        line=line.strip()
        # skip comments.
        if len(line) > 0:
          if line[0] == "#": 
            continue
        
        self.onecmd(self.precmd(line))
    else:
      return super().cmdloop(intro=intro)










  