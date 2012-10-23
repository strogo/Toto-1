'''The Toto package comes with tools that can help make server maintanence and other tasks a little easier.
  Namely, ``TotoService`` can be used to write general processes that take advantage of some of the features
  of ``TotoServer`` and ``TotoWorker`` like process creation/management and the Toto events system.

  Like ``TotoServer``, subclasses of ``TotoService`` can be run with the ``--start`` (or ``--stop--)  and ``--processes`` options
  to run the service as a daemon process or run multiple instances simultaneously.
  
  To run a subclass of ``TotoService`` create a script like this::

    from toto.service import TotoService

    class MyServiceSubclass(TotoService):

      def main_loop(self):
        while 1:
          #run some job continuously

    MyServiceSubclass('conf_file.conf').run()
'''

import os
import tornado
from tornado.options import define, options
import logging
from multiprocessing import Process, cpu_count

define("daemon", metavar='start|stop|restart', help="Start, stop or restart this script as a daemon process. Use this setting in conf files, the shorter start, stop, restart aliases as command line arguments. Requires the multiprocessing module.")
define("processes", default=1, help="The number of daemon processes to run")
define("pidfile", default="toto.daemon.pid", help="The path to the pidfile for daemon processes will be named <path>.<num>.pid (toto.daemon.pid -> toto.daemon.0.pid)")
define("remote_event_receivers", type=str, help="A comma separated list of remote event address that this event manager should connect to. e.g.: 'tcp://192.168.1.2:8889'", multiple=True)
define("event_init_module", default=None, type=str, help="If defined, this module's 'invoke' function will be called with the EventManager instance after the main event handler is registered (e.g.: myevents.setup)")
define("start", default=False, help="Alias for daemon=start for command line usage - overrides daemon setting.")
define("stop", default=False, help="Alias for daemon=start for command line usage - overrides daemon setting.")
define("restart", default=False, help="Alias for daemon=start for command line usage - overrides daemon setting.")
define("nodaemon", default=False, help="Alias for daemon='' for command line usage - overrides daemon setting.")
define("debug", default=False, help="Set this to true to prevent Toto from nicely formatting generic errors. With debug=True, errors will print to the command line")
define("event_port", default=8999, help="The address to listen to event connections on - due to message queuing, servers use the next higher port as well")
define("worker_address", default='', help="This is the address that toto.workerconnection.invoke(method, params) will send tasks too (As specified in the worker conf file)")

#convert p to the absolute path, insert ".i" before the last "." or at the end of the path
def pid_path_with_id(p, i):
  (d, f) = os.path.split(os.path.abspath(p))
  components = f.rsplit('.', 1)
  f = '%s.%s' % (components[0], i)
  if len(components) > 1:
    f += "." + components[1]
  return os.path.join(d, f)

class TotoService():
  '''Subclass ``TotoService`` to create a process that you can easily daemonise and that
  can interact with Toto's event system.
  '''

  def __load_options(self, conf_file=None, **kwargs):
    for k in kwargs:
      options[k].set(kwargs[k])
    if conf_file:
      tornado.options.parse_config_file(conf_file)
    tornado.options.parse_command_line()
    if options.start:
      options['daemon'].set('start')
    elif options.stop:
      options['daemon'].set('stop')
    elif options.restart:
      options['daemon'].set('restart')
    elif options.nodaemon:
      options['daemon'].set('')

  def __init__(self, conf_file=None, **kwargs):
    if options.log_file_prefix:
      root_logger = logging.getLogger()
      for handler in [h for h in root_logger.handlers]:
        root_logger.removeHandler(handler)
    self.__load_options(conf_file, **kwargs)

  def __run_service(self, pidfile=None):

    def start_server_process(pidfile):
      self.main_loop()
      if pidfile:
        os.remove(pidfile)
    count = options.processes if options.processes >= 0 else cpu_count()
    processes = []
    pidfiles = options.daemon and [pid_path_with_id(options.pidfile, i) for i in xrange(1, count + 1)] or []
    for i in xrange(count):
      proc = Process(target=start_server_process, args=(pidfiles and pidfiles[i],))
      proc.daemon = True
      processes.append(proc)
      proc.start()
    else:
      print "Starting %s %s process%s." % (count, self.__class__.__name__, count > 1 and 'es' or '')
    if options.daemon:
      i = 1
      for proc in processes:
        with open(pidfiles[i - 1], 'w') as f:
          f.write(str(proc.pid))
        i += 1
    for proc in processes:
      proc.join()
    if pidfile:
      os.remove(pidfile)

  def run(self): 
    '''Start the service. Depending on the initialization options, this may run more than one
    service process.
    '''
    if options.daemon:
      import multiprocessing
      import signal, re

      pattern = pid_path_with_id(options.pidfile, r'\d+').replace('.', r'\.')
      piddir = os.path.dirname(pattern)

      if options.daemon == 'stop' or options.daemon == 'restart':
        existing_pidfiles = [pidfile for pidfile in (os.path.join(piddir, fn) for fn in os.listdir(os.path.dirname(pattern))) if re.match(pattern, pidfile)]
        for pidfile in existing_pidfiles:
          with open(pidfile, 'r') as f:
            pid = int(f.read())
            try:
              os.kill(pid, signal.SIGTERM)
            except OSError as e:
              if e.errno != 3:
                raise
            print "Stopped %s %s" % (self.__class__.__name__, pid)
          os.remove(pidfile)

      if options.daemon == 'start' or options.daemon == 'restart':
        existing_pidfiles = [pidfile for pidfile in (os.path.join(piddir, fn) for fn in os.listdir(os.path.dirname(pattern))) if re.match(pattern, pidfile)]
        if existing_pidfiles:
          print "Not starting %s, pidfile%s exist%s at %s" % (self.__class__.__name__, len(existing_pidfiles) > 1 and 's' or '', len(existing_pidfiles) == 1 and 's' or '', ', '.join(existing_pidfiles))
          return
        pidfile = pid_path_with_id(options.pidfile, 0)
        #fork and only continue on child process
        if not os.fork():
          #detach from controlling terminal
          os.setsid()
          #fork again and write pid to pidfile from parent, run server on child
          pid = os.fork()
          if pid:
            with open(pidfile, 'w') as f:
              f.write(str(pid))
          else:
            self.__run_service(pidfile)

      if options.daemon not in ('start', 'stop', 'restart'):
        print "Invalid daemon option: " + options.daemon

    else:
      self.__run_service()

  def main_loop(self):
    '''Subclass ``TotoService`` and override ``main_loop()`` with your desired functionality.'''
    raise NotImplementedError()
