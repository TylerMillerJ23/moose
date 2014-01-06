# Load requied packages
import sys, os, pickle, uuid, platform, urllib2
from sets import Set

## @class DmakeRC
#  Manages the .dmakrc file, which stores various information mainly for the purpose
#  of using a cached verision of the DISTCC_HOSTS enviornmental variable for the
#  reason of speeding up the build process.
#
#  Gernerally, the MachineWarehouse automatically manages all aspects of the .dmakerc file
#  via the interface provided by this object.
#
#  @see MachineWarehouse
class DmakeRC(object):

  ## Class constructor
  #  @param master The master machine object
  #  @param kwargs Optional keyword/value parings
  #
  #  Optional Keyword/Value input:
  #    buck = True | {False}      - True to set 'buck' as the remote server
  #    dedicated = True | {False} - True sets the local machine as a dedicated build box on the server
  #    description = <str>        - Set the description of this computer
  #    clean = True | {False}     - remove existing .dmakerc
  #    disable = list()           - A list of username, descriptions, hostnames or ip addresses to disable
  #                                 from DISTCC_HOSTS line (names and numbers may be incomplete)
  #    enable = True | {False}    - Enables all machines that were previously disabled
  def __init__(self, master, **kwargs):

    # List of available items
    self._items = ['HOST_LINES', 'DESCRIPTION', 'DISTCC_HOSTS', 'JOBS', 'DISABLE']

    # Extract the options from the user
    self._test = kwargs.pop('buck', False)
    self._dedicated = kwargs.pop('dedicated', False)

    # Store the local Machine object
    self._master = master

    # Store the complete filename for the .dmakerc file
    self._filename =  os.path.join(os.getenv('HOME'), '.dmakerc')

    # Set the local flag (this is set to true if the remote connection fails, the
    # MachineWarehouse will then use a local build)
    self._fail = False

    # Remove .dmakerc if clean option is given
    if kwargs.pop('clean', False):
      if os.path.exists(self._filename):
        os.remove(self._filename)

    # Initialize the update variable, this value is True when when
    # the DISTCC_HOSTS stored is out-of-date
    self._update_distcc_hosts = False

    # Read the .dmakerc, stored as a dictionary which is accessible via
    # the get/set methods of this object
    self._dmakerc, local_ip = self._readLocalFile()

    # Set/update the user supplied description of the local machine
    self._checkDescription(kwargs.pop('description', None))

    # Read the remote machine file from the server, if nothing has changed
    # this list will be identical to the HOST_LINES item in the self._dmakerc
    # dictionary
    self._remote, remote_ip = self._readRemoteFile()

    # Check if the ip address differ between the local and remote lists, if so
    # indicate an update is needed
    if remote_ip != local_ip:
      print remote_ip, local_ip
      self._update_distcc_hosts = True

    # Return if the remote connection fails
    if self._remote == None:
      self._fail = True
      return

    # Set the stored HOST_LINES to be the same as the server
    self.set(HOST_LINES=self._remote)

    # Enable previously disabled machines, requires update
    if kwargs.pop('enable', False):
      self.set(DISABLE=None)
      self._update_distcc_hosts = True

    # Set the disable list to be the same as the input, requires update
    if kwargs['disable'] != None:
      self.set(DISABLE=kwargs['disable'])
      self._update_distcc_hosts = True


  ## Accessor for stored variables (public)
  #  @param key The name of the dictionary item to retrun (e.g., 'DISTCC_HOSTS')
  #  @return The value from the dictionary for the given key, it will return None
  #          if the key is not found
  def get(self, key):
    if key not in self._dmakerc:
      return None
    else:
      return self._dmakerc[key]


  ## Method for storing data (public)
  #  @param kwargs Key/value pairings that include the variables to set as well
  #                as optional triggers
  #
  #  Available keywords for storing data:
  #    DISTCC_HOSTS = <str>     - String containing the complete DISTCC_HOSTS enviornmental variable
  #    JOBS = <int>             - No. of processes to utilize for 'make'
  #    DESCRIPTION = <str>      - String containing description of this machine
  #    HOST_LINES = list(<str>) - A list of raw strings, with each entry representing a remote machine, as
  #                               read from the server
  #    DISABLE = list           - A list of username, description, hostname, or ip addresses to ignore
  #
  #  Optional keywords available:
  #    write = {True} | False   - Toggle the writting of the .dmakerc file if something is changes
  #
  #  Example:
  #    set(DISTCC_HOSTS=hosts, JOBS=4, write=False)
  def set(self, **kwargs):

    # Flag for writting file
    write = kwargs.pop('write', True)

    # Loop through the keyword/value pairs
    for key, value in kwargs.iteritems():

     # Error if the key is unknown
     if key not in self._items:
       print 'Error: Unknown key ' + key
       sys.exit()

     # If the key is not in the dictionary or it has changed, update the value
     if (key not in self._dmakerc) or (self._dmakerc[key] != value):
       self._dmakerc[key] = value

    # Store the change to the file (this is allways done unless specified)
    if write:
      fid = open(self._filename, 'w')
      pickle.dump(self._dmakerc, fid)
      fid.close()


  ## Was the .dmakerc file updated (public)
  #  @return True if the DISTCC_HOSTS variable needs to be updated
  def distccHostsNeedsUpdate(self):
    if self.get('DISTCC_HOSTS') == None:
      return True
    else:
      return self._update_distcc_hosts


  ## Return the status of the remote access (public)
  # @return True if the remote connection failed
  def fail(self):
    return self._fail


  ## Reads the local .dmakerc file (private)
  # @return A map of the data loaded from the .dmakerc
  def _readLocalFile(self):

    # An empty set of IP addresses
    ip = Set()

    # Read the file, if it exists
    if os.path.exists(self._filename):
      fid = open(self._filename, 'r')
      data = pickle.load(fid)
      fid.close()
    else:
      data = dict()
      for item in self._items:
        data.setdefault(item, None)

    # Clean up the hostlines
    if data['HOST_LINES'] != None:
      data['HOST_LINES'], ip = self._cleanHostLines(data['HOST_LINES'])

    # Return the data
    return data, ip


  ## Reads the remote machine list (private)
  # @return A map of the data loaded from the .dmakerc
  def _readRemoteFile(self):

    # Define the servers
    buck =  dict(url='https://buck.inl.gov/distcc_gen', name='buck')
    hpcsc = dict(url='https://hpcsc.inl.gov/distcc_gen', name='hpcsc')

    # Get the remote location to utilize
    if self._test:
      remote = buck
      backup = hpcsc
    else:
      remote = hpcsc
      backup = buck

    # Set the 'use_threads' attribute for this machine
    if self._dedicated:
      self._master.use_threads = (int(self._master.threads) / 2)
    else:
      self._master.use_threads = (int(self._master.threads) / 4)

    # Read the data from the server
    data = self._urlOpen(remote)

    # If data doesn't exist try the backup
    if data == None:
      data = self._urlOpen(backup)

    # If it still dosen't exist, run locally
    if data == None:
      return None

    # Return the host lines from the remote server
    lines, ip = self._cleanHostLines(data)
    return lines, ip

  ## Create/override the user supplied description (private)
  #  @param description A description of this machine
  def _checkDescription(self, description):

    # Set the description via the input argument
    if description != None:
      self.set(DESCRIPTION = description[0])

    # If the description is empty, prompt the user
    if self.get('DESCRIPTION') == None:
      print 'Supply a description of your machine:'
      while self.get('DESCRIPTION') == None:
        self.set(DESCRIPTION=sys.stdin.readline().split('\n')[0])

    # Update the description of this machine
    self._master.description = self.get('DESCRIPTION')
    self._master._computeLength()


  ## Cleans up the raw HOST_LINES input (private)
  #  @param input The list of raw HOST_LINES from the server or .dmakerc file
  #  @return A sorted list that does not contain duplicate IP addresses and a sorted list of IP addresses
  #
  #  Example:
  #    host_lines, ip = _cleanHostLines()
  def _cleanHostLines(self, input):

    # Create an empty set for storing unique IP addresses
    ip = Set()

    # Remove any empty rows from the raw file
    input = filter(None, input)

    # Initialize output list
    output = []

    # Loop throught the input
    for line in input:

      # Previous versions of the .dmakerc file store the HOST_LINES in raw format as a list of non-split strings,
      # so this must be accounted for or else things fail. So, if the line is already a list then continue,
      # otherwise the line must be split
      if not isinstance(line, list):
        line = line.split(',')

      # Extract the IP address
      address = line[0]

      # If IP address has not been encountered and it is not this machine and it is not 127.0.0.1
      # add the raw line to the output
      if (address not in ip) and (address != self._master.address) and (address != '127.0.0.1'):
        output.append(line)
        ip.add(address)

    # Sort the output and return it
    output.sort()
    return output, ip


  ## Access the server
  # @param input Dictionary with url and name parameters for the remote server
  # @return The data from the server if sucessfull, or None if it fails
  def _urlOpen(self, input):

    # Set the url to send to the remote server
    filename = input['url'] + '?uuid=' + str(uuid.uuid3(uuid.NAMESPACE_DNS, self._master.hostname)) + \
                 '&arch=' + platform.system().lower() + \
                 '&ip=' + self._master.address + \
                 '&cpus=' + str(self._master.threads) + \
                 '&threads=' + str(self._master.threads) + \
                 '&use=' + str(self._master.use_threads) + \
                 '&network=' + self._master.network + \
                 '&description=' + urllib2.quote(self._master.description) + \
                 '&username=' + os.getenv('USER')

    try:
      fid = urllib2.urlopen(filename, None, 1)
      data = fid.read().split('\n')
      fid.close()
      return data

    except:
      print 'Warning: Failed to connect to ' + input['name']
      return None
